from datetime import datetime, timezone

from chromadb.api.models.Collection import Collection
from openai import OpenAI
from sqlmodel import Session, select

from app.classification.categories import UNCATEGORIZED
from app.db.models import Message
from app.retrieval.embeddings import embed_texts
from app.retrieval.fts import ensure_fts_table, upsert_fts
from app.util import chunks

BODY_CHARS_FOR_EMBEDDING = 6000
EMBED_BATCH_SIZE = 50


def index_pending_messages(
    session: Session, collection: Collection, client: OpenAI, limit: int = 1000, since: datetime | None = None
) -> dict:
    ensure_fts_table(session)

    new_query = select(Message).where(Message.indexed_at.is_(None))
    if since is not None:
        new_query = new_query.where(Message.internal_date >= since)
    new_messages = session.exec(new_query.limit(limit)).all()

    embedded = 0
    for batch in chunks(new_messages, EMBED_BATCH_SIZE):
        _embed_and_upsert(session, collection, client, batch)
        embedded += len(batch)

    # Messages already embedded but changed since (new label, freshly
    # classified) only need their metadata refreshed, not re-embedded.
    stale_query = (
        select(Message)
        .where(Message.indexed_at.is_not(None))
        .where(Message.updated_at > Message.indexed_at)
    )
    if since is not None:
        stale_query = stale_query.where(Message.internal_date >= since)
    stale = session.exec(stale_query.limit(limit)).all()
    for msg in stale:
        collection.update(ids=[msg.id], metadatas=[_build_metadata(msg)])
        upsert_fts(session, msg)
        msg.indexed_at = datetime.now(timezone.utc)
        session.add(msg)
    session.commit()

    return {"embedded": embedded, "metadata_refreshed": len(stale)}


def _embed_and_upsert(
    session: Session, collection: Collection, client: OpenAI, batch: list[Message]
) -> None:
    documents = [_build_document(m) for m in batch]
    vectors = embed_texts(client, documents)

    collection.upsert(
        ids=[m.id for m in batch],
        embeddings=vectors,
        documents=documents,
        metadatas=[_build_metadata(m) for m in batch],
    )

    for msg in batch:
        upsert_fts(session, msg)
        msg.indexed_at = datetime.now(timezone.utc)
        session.add(msg)
    session.commit()


def _build_document(m: Message) -> str:
    date_str = m.internal_date.isoformat() if m.internal_date else ""
    body = m.body_text[:BODY_CHARS_FOR_EMBEDDING]
    return f"From: {m.sender_name} <{m.sender_email}>\nDate: {date_str}\nSubject: {m.subject}\n\n{body}"


def _build_metadata(m: Message) -> dict:
    return {
        "sender_email": m.sender_email,
        "subject": m.subject,
        "category": m.category or UNCATEGORIZED,
        "is_unread": m.is_unread,
        "internal_date_ts": int(m.internal_date.timestamp()) if m.internal_date else 0,
    }
