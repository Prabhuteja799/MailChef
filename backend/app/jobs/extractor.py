import json
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from sqlmodel import Session, select

from app.config import settings
from app.db.models import JobApplication, JobApplicationEvent, Message
from app.jobs.matcher import company_key
from app.jobs.types import EventType
from app.llm import INJECTION_GUARD
from app.util import chunks

BATCH_SIZE = 15
BODY_CHARS = 800

# Personal/promotion mail is never a job-application signal — restricting to
# these keeps the (potentially large) extraction pass cheap.
JOB_RELEVANT_CATEGORIES = {"interview", "recruiter", "update"}


def extract_job_events(
    session: Session, client: OpenAI, limit: int = 1000, since: datetime | None = None
) -> dict:
    query = (
        select(Message)
        .where(Message.job_extracted_at.is_(None))
        .where(Message.category.in_(JOB_RELEVANT_CATEGORIES))
    )
    if since is not None:
        query = query.where(Message.internal_date >= since)
    pending = session.exec(query.limit(limit)).all()

    events_recorded = 0
    applications_touched: set[str] = set()

    for batch in chunks(pending, BATCH_SIZE):
        results = _extract_batch(client, batch)
        for msg in batch:
            result = results.get(msg.id)
            if result and result["is_job_related"]:
                app_id = _upsert_application(session, msg, result)
                applications_touched.add(app_id)
                events_recorded += 1
            msg.job_extracted_at = datetime.now(timezone.utc)
            session.add(msg)
        session.commit()

    return {
        "messages_scanned": len(pending),
        "events_recorded": events_recorded,
        "applications_touched": len(applications_touched),
    }


def _extract_batch(client: OpenAI, batch: list[Message]) -> dict[str, dict]:
    event_types = [e.value for e in EventType]
    emails_block = "\n\n".join(
        f"id: {m.id}\nfrom: {m.sender_name} <{m.sender_email}>\nsubject: {m.subject}\n"
        f"body: {m.body_text[:BODY_CHARS]}"
        for m in batch
    )

    system = (
        f"{INJECTION_GUARD}\n\n"
        "You scan emails to find ones related to a job application the user "
        "personally submitted, and extract structured tracking info. For "
        "each email, decide is_job_related. If true, extract:\n"
        "- company: the parent brand/company name, not the ATS platform or "
        'a verbose subsidiary/team name (e.g. "Citi" not "Citi Scaled '
        'Technical Hiring NAM", "Palantir" not "Palantir Technologies '
        'Careers Team")\n'
        '- role: the job title mentioned, or "" if none is stated\n'
        f"- event_type: one of {event_types}\n"
        "  - applied: confirms an application was submitted/received\n"
        '  - acknowledged: generic "we received it, we\'ll review" with no other signal\n'
        "  - interview: invites you to schedule or confirms an interview/assessment\n"
        "  - moving_forward: explicitly advancing to a next round / positive news short of an offer\n"
        "  - offer: a job offer\n"
        "  - rejected: explicitly not moving forward / another candidate selected / role filled\n"
        "  - other: job-related but doesn't fit the above\n"
        "- summary: one crisp sentence\n"
        'If is_job_related is false, still fill company/role/summary with "" '
        'and event_type with "other".'
    )

    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "is_job_related": {"type": "boolean"},
                        "company": {"type": "string"},
                        "role": {"type": "string"},
                        "event_type": {"type": "string", "enum": event_types},
                        "summary": {"type": "string"},
                    },
                    "required": ["id", "is_job_related", "company", "role", "event_type", "summary"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["results"],
        "additionalProperties": False,
    }

    response = client.chat.completions.create(
        model=settings.classifier_model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": emails_block},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "job_events", "strict": True, "schema": schema},
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    valid_ids = {m.id for m in batch}
    return {item["id"]: item for item in parsed["results"] if item["id"] in valid_ids}


def _upsert_application(session: Session, msg: Message, result: dict) -> str:
    key = company_key(result["company"]) or (result["company"].strip().lower() or "unknown")
    event_date = msg.internal_date or datetime.now(timezone.utc)

    existing = session.exec(select(JobApplication).where(JobApplication.company_key == key)).first()

    if existing is None:
        application = JobApplication(
            id=uuid.uuid4().hex,
            company=result["company"] or "Unknown",
            company_key=key,
            role=result["role"] or None,
            status=result["event_type"],
            status_updated_at=event_date,
        )
        session.add(application)
        session.flush()  # populate application.id before the event FK below
        app_id = application.id
    else:
        app_id = existing.id
        if event_date >= existing.status_updated_at:
            existing.status = result["event_type"]
            existing.status_updated_at = event_date
            if result["role"]:
                existing.role = result["role"]
            session.add(existing)

    session.add(
        JobApplicationEvent(
            id=uuid.uuid4().hex,
            application_id=app_id,
            message_id=msg.id,
            event_type=result["event_type"],
            event_date=event_date,
            summary=result["summary"],
        )
    )
    return app_id
