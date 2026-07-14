import logging
from datetime import datetime, timezone

from googleapiclient.errors import HttpError
from sqlmodel import Session, select

from app.config import settings
from app.db.models import Message, SyncState
from app.gmail.client import GmailClient, ParsedMessage

logger = logging.getLogger(__name__)


def run_sync(session: Session, client: GmailClient) -> dict:
    state = session.exec(select(SyncState)).first() or SyncState()

    if state.last_history_id is None:
        result = _full_backfill(session, client, state)
    else:
        try:
            result = _incremental_sync(session, client, state)
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning("history id too old, falling back to full backfill")
                result = _full_backfill(session, client, state)
            else:
                raise

    state.last_synced_at = datetime.now(timezone.utc)
    session.add(state)
    session.commit()
    return result


def _full_backfill(session: Session, client: GmailClient, state: SyncState) -> dict:
    query = f"newer_than:{settings.initial_sync_days}d"
    fetched = 0
    page_token = None

    while True:
        ids, page_token = client.list_message_ids(query=query, page_token=page_token)
        for msg_id in ids:
            _upsert_message(session, client.get_message(msg_id))
            fetched += 1
        if not page_token:
            break

    session.commit()
    state.last_history_id = client.get_profile()["historyId"]
    return {"mode": "full_backfill", "messages_fetched": fetched}


def _incremental_sync(session: Session, client: GmailClient, state: SyncState) -> dict:
    touched_ids: set[str] = set()
    page_token = None

    while True:
        records, page_token = client.list_history(state.last_history_id, page_token=page_token)
        for record in records:
            for key in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                for entry in record.get(key, []):
                    touched_ids.add(entry["message"]["id"])
        if not page_token:
            break

    for msg_id in touched_ids:
        _upsert_message(session, client.get_message(msg_id))

    session.commit()
    state.last_history_id = client.get_profile()["historyId"]
    return {"mode": "incremental", "messages_touched": len(touched_ids)}


def _upsert_message(session: Session, parsed: ParsedMessage) -> None:
    existing = session.get(Message, parsed.id)
    row = existing or Message(id=parsed.id, thread_id=parsed.thread_id)

    row.thread_id = parsed.thread_id
    row.sender_name = parsed.sender_name
    row.sender_email = parsed.sender_email
    row.to_recipients = parsed.to_recipients
    row.subject = parsed.subject
    row.snippet = parsed.snippet
    row.body_text = parsed.body_text
    row.internal_date = parsed.internal_date
    row.label_ids = ",".join(parsed.label_ids)
    row.is_unread = parsed.is_unread
    row.updated_at = datetime.now(timezone.utc)

    session.add(row)
