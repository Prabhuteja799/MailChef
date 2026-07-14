import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dateutil import parser as date_parser
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.actions.service import (
    ActionError,
    cancel_pending_action,
    confirm_pending_action,
    create_pending_action,
    execute_immediate,
)
from app.actions.types import ActionType
from app.auth.api_auth import require_api_token
from app.auth.gmail_oauth import (
    exchange_code_for_credentials,
    get_authorization_url,
    load_credentials,
    save_credentials,
)
from app.classification.categories import load_categories
from app.classification.classifier import classify_pending_messages
from app.db.database import create_db_and_tables, engine, get_session
from app.db.models import Digest, JobApplication, JobApplicationEvent, Message
from app.digest.generator import digest_to_dict
from app.digest.pipeline import run_full_pipeline
from app.digest.scheduler import start_scheduler, stop_scheduler
from app.gmail.client import GmailClient
from app.gmail.sync import refresh_message_bodies, run_sync
from app.jobs.extractor import extract_job_events
from app.llm import get_openai_client
from app.query.answer import answer_question
from app.retrieval.fts import ensure_fts_table
from app.retrieval.indexer import index_pending_messages
from app.retrieval.search import SearchFilters, hybrid_search
from app.retrieval.vectorstore import get_collection

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="MailChef")

# Permissive CORS for the web UI talking to this API cross-origin (e.g. the
# Vite dev server on :5173 during local frontend development). Safe here
# because auth is a bearer token on every request, not a cookie — CORS
# doesn't weaken that. In production the built frontend is served from this
# same origin (see the StaticFiles mount at the bottom of this file), so
# CORS isn't even in play there.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ActionError)
def handle_action_error(request: Request, exc: ActionError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        ensure_fts_table(session)
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Gmail OAuth: one-time, human-in-the-browser flow. Not behind the API
# bearer token, since it's a bootstrapping step done before that token is
# useful — instead it's protected by knowledge of the deployed URL plus
# Google's own consent screen. ---


@app.get("/auth/gmail/start")
def auth_start() -> dict:
    return {"authorization_url": get_authorization_url()}


@app.get("/auth/gmail/callback", response_class=HTMLResponse)
def auth_callback(code: str, session: Session = Depends(get_session)) -> str:
    try:
        credentials = exchange_code_for_credentials(code)
    except OAuth2Error as e:
        logging.getLogger(__name__).error("OAuth token exchange failed: %s", e.description or str(e))
        return (
            f"<html><body><h3>Gmail connection failed: {e.description or e}</h3>"
            "<p>Go back to /auth/gmail/start and try again — authorization codes are "
            "single-use, so this one is no longer valid either way.</p></body></html>"
        )
    save_credentials(session, credentials)
    return "<html><body><h3>MailChef connected to Gmail. You can close this tab.</h3></body></html>"


def _require_gmail_client(session: Session) -> GmailClient:
    credentials = load_credentials(session)
    if credentials is None:
        raise HTTPException(400, "Gmail not connected yet — visit /auth/gmail/start first")
    return GmailClient(credentials)


@app.post("/sync/run", dependencies=[Depends(require_api_token)])
def sync_run(session: Session = Depends(get_session)) -> dict:
    client = _require_gmail_client(session)
    return run_sync(session, client)


@app.post("/messages/refresh-bodies", dependencies=[Depends(require_api_token)])
def messages_refresh_bodies(
    limit: int = Query(default=500, le=2000),
    since_days: int | None = Query(default=None, description="Only refresh mail from the last N days."),
    session: Session = Depends(get_session),
) -> dict:
    """Re-fetches body_text for already-synced mail — for backfilling a
    body-extraction fix onto messages synced before the fix existed. Call
    repeatedly (it processes most-recent-first) until `refreshed` < limit.
    """
    since = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    client = _require_gmail_client(session)
    return refresh_message_bodies(session, client, limit=limit, since=since)


@app.get("/messages", dependencies=[Depends(require_api_token)])
def list_messages(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    category: str | None = None,
    sender: str | None = None,
    after: str | None = None,
    before: str | None = None,
    unread_only: bool = False,
    session: Session = Depends(get_session),
) -> list[dict]:
    """Browse mail sorted by date (most recent first), optionally filtered —
    this is the "just show me my inbox, like Gmail" view, as opposed to
    /search which is relevance-ranked and requires a query.
    """
    query = select(Message)
    if category:
        query = query.where(Message.category == category)
    if sender:
        query = query.where(Message.sender_email.contains(sender))
    if after:
        query = query.where(Message.internal_date >= date_parser.parse(after))
    if before:
        query = query.where(Message.internal_date <= date_parser.parse(before))
    if unread_only:
        query = query.where(Message.is_unread == True)  # noqa: E712

    rows = session.exec(
        query.order_by(Message.internal_date.desc()).offset(offset).limit(limit)
    ).all()
    return [_message_summary(m) for m in rows]


@app.get("/messages/{message_id}", dependencies=[Depends(require_api_token)])
def get_message(message_id: str, session: Session = Depends(get_session)) -> dict:
    """Full email content — the summary list only carries a short snippet,
    this is what backs an "open this email" reading view.
    """
    m = session.get(Message, message_id)
    if m is None:
        raise HTTPException(404, "No such message")
    return {
        **_message_summary(m),
        "to": m.to_recipients,
        "body_text": m.body_text,
    }


# --- Stage (b): classification + retrieval ---


@app.get("/categories", dependencies=[Depends(require_api_token)])
def get_categories() -> list[dict]:
    return [c.model_dump() for c in load_categories()]


@app.post("/classify/run", dependencies=[Depends(require_api_token)])
def classify_run(
    since_days: int | None = Query(default=None, description="Only classify mail from the last N days."),
    session: Session = Depends(get_session),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    return classify_pending_messages(session, get_openai_client(), since=since)


@app.post("/index/run", dependencies=[Depends(require_api_token)])
def index_run(
    since_days: int | None = Query(default=None, description="Only index mail from the last N days."),
    session: Session = Depends(get_session),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    return index_pending_messages(session, get_collection(), get_openai_client(), since=since)


@app.get("/search", dependencies=[Depends(require_api_token)])
def search(
    q: str,
    category: str | None = None,
    sender: str | None = None,
    after: str | None = None,
    before: str | None = None,
    unread_only: bool = False,
    limit: int = Query(default=20, le=100),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Raw hybrid retrieval, no LLM synthesis — lets us verify search quality
    before stage (c) layers query answering on top of this.
    """
    filters = SearchFilters(
        category=category,
        sender_contains=sender,
        after=date_parser.parse(after) if after else None,
        before=date_parser.parse(before) if before else None,
        unread_only=unread_only,
    )
    results = hybrid_search(session, get_collection(), get_openai_client(), q, filters, limit)
    return [_message_summary(m) for m in results]


# --- Stage (c): query answering ---


class QueryRequest(BaseModel):
    question: str


@app.post("/query", dependencies=[Depends(require_api_token)])
def query(body: QueryRequest, session: Session = Depends(get_session)) -> dict:
    client = get_openai_client()
    return answer_question(session, get_collection(), client, body.question)


# --- Stage (d): inbox actions with confirmation ---


@app.get("/labels", dependencies=[Depends(require_api_token)])
def list_labels(session: Session = Depends(get_session)) -> list[dict]:
    return _require_gmail_client(session).list_labels()


class ActionRequest(BaseModel):
    action: str
    message_ids: list[str] | None = None
    # Alternative to message_ids: resolve the target via the same hybrid
    # search used by /search and /query, so a caller (CLI or a future
    # tool-calling chat) can say "archive the promo emails" without knowing
    # ids up front. This only ever searches subject/sender/body as data —
    # it never lets email content decide what action to take.
    search: str | None = None
    category: str | None = None
    sender: str | None = None
    after: str | None = None
    before: str | None = None
    unread_only: bool = False
    limit: int = 100
    label_name: str | None = None


def _resolve_action_type(action: str) -> ActionType:
    try:
        return ActionType(action)
    except ValueError:
        valid = ", ".join(a.value for a in ActionType)
        raise HTTPException(400, f"Unknown action {action!r}. Valid actions: {valid}")


def _resolve_target_ids(body: ActionRequest, session: Session) -> list[str]:
    if body.message_ids:
        return body.message_ids
    if body.search:
        filters = SearchFilters(
            category=body.category,
            sender_contains=body.sender,
            after=date_parser.parse(body.after) if body.after else None,
            before=date_parser.parse(body.before) if body.before else None,
            unread_only=body.unread_only,
        )
        results = hybrid_search(session, get_collection(), get_openai_client(), body.search, filters, body.limit)
        return [m.id for m in results]
    raise HTTPException(400, "Provide either message_ids or search")


@app.post("/actions/propose", dependencies=[Depends(require_api_token)])
def actions_propose(body: ActionRequest, session: Session = Depends(get_session)) -> dict:
    """Resolves the target emails and stores a confirmable proposal — does
    NOT touch Gmail yet. The caller must show `affected` to the user and
    only call /actions/confirm if they explicitly say yes.
    """
    action = _resolve_action_type(body.action)
    gmail_client = _require_gmail_client(session)
    message_ids = _resolve_target_ids(body, session)

    pending, messages = create_pending_action(session, gmail_client, action, message_ids, body.label_name)
    return {
        "proposal_id": pending.id,
        "action": pending.action,
        "expires_at": pending.expires_at.isoformat(),
        "affected_count": len(messages),
        "affected": [_message_summary(m) for m in messages],
    }


class ConfirmRequest(BaseModel):
    proposal_id: str


@app.post("/actions/confirm", dependencies=[Depends(require_api_token)])
def actions_confirm(body: ConfirmRequest, session: Session = Depends(get_session)) -> dict:
    gmail_client = _require_gmail_client(session)
    return confirm_pending_action(session, gmail_client, body.proposal_id)


@app.post("/actions/cancel", dependencies=[Depends(require_api_token)])
def actions_cancel(body: ConfirmRequest, session: Session = Depends(get_session)) -> dict:
    cancelled = cancel_pending_action(session, body.proposal_id)
    if not cancelled:
        raise HTTPException(404, "No such pending proposal (or it was already executed)")
    return {"cancelled": True}


@app.post("/actions/execute", dependencies=[Depends(require_api_token)])
def actions_execute(body: ActionRequest, session: Session = Depends(get_session)) -> dict:
    """Immediate execution for safe, single-target, reversible actions only
    (single mark read/unread, star/unstar, add/remove label). Destructive
    actions (archive, trash) and anything touching more than one message
    are rejected here — they must go through propose/confirm.
    """
    action = _resolve_action_type(body.action)
    gmail_client = _require_gmail_client(session)
    message_ids = _resolve_target_ids(body, session)
    return execute_immediate(session, gmail_client, action, message_ids, body.label_name)


# --- Stage (e): scheduled + on-demand morning digest ---


@app.post("/digest/run", dependencies=[Depends(require_api_token)])
def digest_run(
    since_days: int | None = Query(
        default=None, description="Classify/index mail from the last N days (defaults to INITIAL_SYNC_DAYS)."
    ),
    session: Session = Depends(get_session),
) -> dict:
    """"Give me my summary now" — syncs, classifies, re-indexes, and
    generates a fresh digest, same pipeline the scheduled job runs.
    """
    gmail_client = _require_gmail_client(session)
    return run_full_pipeline(session, gmail_client, get_openai_client(), get_collection(), since_days=since_days)


@app.get("/digest/latest", dependencies=[Depends(require_api_token)])
def digest_latest(session: Session = Depends(get_session)) -> dict:
    digest = session.exec(select(Digest).order_by(Digest.generated_at.desc())).first()
    if digest is None:
        raise HTTPException(404, "No digest has been generated yet — try POST /digest/run")
    return digest_to_dict(digest)


# --- Job application tracker ---


@app.post("/jobs/extract", dependencies=[Depends(require_api_token)])
def jobs_extract(
    since_days: int | None = Query(default=None, description="Only scan mail from the last N days."),
    session: Session = Depends(get_session),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=since_days) if since_days else None
    return extract_job_events(session, get_openai_client(), since=since)


@app.get("/jobs", dependencies=[Depends(require_api_token)])
def jobs_list(session: Session = Depends(get_session)) -> list[dict]:
    applications = session.exec(
        select(JobApplication).order_by(JobApplication.status_updated_at.desc())
    ).all()
    return [_job_application_summary(session, a) for a in applications]


@app.get("/jobs/{application_id}", dependencies=[Depends(require_api_token)])
def jobs_detail(application_id: str, session: Session = Depends(get_session)) -> dict:
    application = session.get(JobApplication, application_id)
    if application is None:
        raise HTTPException(404, "No such application")

    events = session.exec(
        select(JobApplicationEvent)
        .where(JobApplicationEvent.application_id == application_id)
        .order_by(JobApplicationEvent.event_date.desc())
    ).all()

    return {
        **_job_application_summary(session, application),
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "event_date": e.event_date.isoformat(),
                "summary": e.summary,
                "source_message": _message_summary(session.get(Message, e.message_id))
                if session.get(Message, e.message_id)
                else None,
            }
            for e in events
        ],
    }


def _job_application_summary(session: Session, a: JobApplication) -> dict:
    event_count = session.exec(
        select(func.count())
        .select_from(JobApplicationEvent)
        .where(JobApplicationEvent.application_id == a.id)
    ).one()
    return {
        "id": a.id,
        "company": a.company,
        "role": a.role,
        "status": a.status,
        "status_updated_at": a.status_updated_at.isoformat(),
        "event_count": event_count,
    }


def _message_summary(m: Message) -> dict:
    return {
        "id": m.id,
        "from": f"{m.sender_name} <{m.sender_email}>",
        "subject": m.subject,
        "date": m.internal_date.isoformat() if m.internal_date else None,
        "unread": m.is_unread,
        "category": m.category,
        "snippet": m.snippet,
    }


# --- Web UI: serve the built React app. Mounted last so it never shadows
# an API route above — Starlette matches routes in registration order, and
# this only catches whatever no earlier route claimed. html=True serves
# index.html for any unmatched path, since navigation is in-app tab state
# rather than real URL routes. ---
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
else:
    logging.getLogger(__name__).warning(
        "web/dist not found — web UI not mounted. Run `npm run build` in web/ to enable it."
    )
