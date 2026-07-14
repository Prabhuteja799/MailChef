from datetime import datetime, timedelta, timezone

from chromadb.api.models.Collection import Collection
from openai import OpenAI
from sqlmodel import Session

from app.classification.classifier import classify_pending_messages
from app.config import settings
from app.db.models import Digest
from app.digest.generator import generate_digest
from app.gmail.client import GmailClient
from app.gmail.sync import run_sync
from app.jobs.extractor import extract_job_events
from app.retrieval.indexer import index_pending_messages


def run_full_pipeline(
    session: Session,
    gmail_client: GmailClient,
    openai_client: OpenAI,
    collection: Collection,
    since_days: int | None = None,
) -> dict:
    """Sync -> classify -> index -> extract job events -> digest, in that
    order, so the digest reflects the freshest inbox state (including
    freshly-detected interview/reply/rejection events). Used both by the
    scheduled job and the on-demand /digest/run endpoint.

    classify/index/job-extraction are scoped to the last `since_days`
    (defaulting to settings.initial_sync_days) rather than the whole local
    archive — a full Gmail backfill can leave thousands of older messages
    pending, and reprocessing all of them on every digest run would be
    needlessly slow and expensive. Older mail can still be processed
    explicitly via /classify/run, /index/run, /jobs/extract with a larger or
    no since_days.
    """
    days = since_days if since_days is not None else settings.initial_sync_days
    since = datetime.now(timezone.utc) - timedelta(days=days)

    sync_result = run_sync(session, gmail_client)
    classify_result = classify_pending_messages(session, openai_client, since=since)
    index_result = index_pending_messages(session, collection, openai_client, since=since)
    jobs_result = extract_job_events(session, openai_client, since=since)
    digest = generate_digest(session, openai_client)

    return {
        "sync": sync_result,
        "classify": classify_result,
        "index": index_result,
        "jobs": jobs_result,
        "digest": _digest_summary(digest),
    }


def _digest_summary(digest: Digest) -> dict:
    return {
        "id": digest.id,
        "generated_at": digest.generated_at.isoformat(),
        "unread_count": digest.unread_count,
        "content_markdown": digest.content_markdown,
    }
