import re

from sqlalchemy import text
from sqlmodel import Session

from app.db.models import Message

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


def ensure_fts_table(session: Session) -> None:
    session.execute(
        text("CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(id UNINDEXED, subject, sender, body)")
    )
    session.commit()


def upsert_fts(session: Session, message: Message) -> None:
    session.execute(text("DELETE FROM message_fts WHERE id = :id"), {"id": message.id})
    session.execute(
        text("INSERT INTO message_fts (id, subject, sender, body) VALUES (:id, :subject, :sender, :body)"),
        {
            "id": message.id,
            "subject": message.subject,
            "sender": f"{message.sender_name} {message.sender_email}",
            "body": message.body_text,
        },
    )


def search_fts(session: Session, query: str, limit: int = 20) -> list[str]:
    match_query = _to_match_query(query)
    if not match_query:
        return []

    rows = session.execute(
        text(
            "SELECT id FROM message_fts WHERE message_fts MATCH :q "
            "ORDER BY bm25(message_fts) LIMIT :limit"
        ),
        {"q": match_query, "limit": limit},
    ).all()
    return [row[0] for row in rows]


def _to_match_query(query: str) -> str | None:
    """Free-text user queries can contain characters that break FTS5's MATCH
    syntax (colons, hyphens, quotes). Reduce to a safe OR-of-terms query
    instead of passing the raw string through.
    """
    tokens = _TOKEN_RE.findall(query)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens)
