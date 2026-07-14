import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from app.auth.gmail_oauth import load_credentials
from app.config import settings
from app.db.database import engine
from app.digest.pipeline import run_full_pipeline
from app.gmail.client import GmailClient
from app.llm import get_openai_client
from app.retrieval.vectorstore import get_collection

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_scheduled_digest() -> None:
    with Session(engine) as session:
        credentials = load_credentials(session)
        if credentials is None:
            logger.warning("scheduled digest skipped: Gmail not connected yet")
            return
        try:
            run_full_pipeline(session, GmailClient(credentials), get_openai_client(), get_collection())
            logger.info("scheduled digest generated")
        except Exception:
            logger.exception("scheduled digest failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=settings.digest_timezone)
    scheduler.add_job(
        _run_scheduled_digest,
        CronTrigger(hour=settings.digest_hour, minute=settings.digest_minute),
        id="morning_digest",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
