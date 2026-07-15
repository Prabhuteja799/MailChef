from dataclasses import dataclass
from datetime import datetime

from chromadb.api.models.Collection import Collection
from openai import OpenAI
from sqlmodel import Session, select

from app.config import settings
from app.db.models import Message
from app.retrieval.embeddings import embed_texts
from app.retrieval.fts import search_fts

RRF_K = 60  # standard reciprocal-rank-fusion constant


@dataclass
class SearchFilters:
    category: str | None = None
    sender_contains: str | None = None
    after: datetime | None = None
    before: datetime | None = None
    unread_only: bool = False


def list_by_filters(session: Session, filters: SearchFilters, limit: int = 50) -> list[Message]:
    """Date-ordered, no semantic/keyword ranking involved — for "give me
    everything from today" style requests. hybrid_search ranks by topical
    relevance to a search string, which is the wrong tool for "list every
    email in this window": a generic query like "report" or "summary" has
    weak embedding signal, so genuinely in-range emails can easily miss a
    fixed top-K relevance cut merely for not sounding enough like the query.
    """
    query = select(Message)
    if filters.category:
        query = query.where(Message.category == filters.category)
    if filters.sender_contains:
        query = query.where(Message.sender_email.contains(filters.sender_contains))
    if filters.after:
        query = query.where(Message.internal_date >= filters.after)
    if filters.before:
        query = query.where(Message.internal_date <= filters.before)
    if filters.unread_only:
        query = query.where(Message.is_unread == True)  # noqa: E712

    return list(session.exec(query.order_by(Message.internal_date.desc()).limit(limit)).all())


def hybrid_search(
    session: Session,
    collection: Collection,
    client: OpenAI,
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 20,
) -> list[Message]:
    filters = filters or SearchFilters()
    fetch_n = limit * 3  # over-fetch before filtering, since filters are applied post-hoc

    semantic_ids = _semantic_search(collection, client, query, fetch_n)
    keyword_ids = search_fts(session, query, fetch_n)

    scores: dict[str, float] = {}
    for rank, msg_id in enumerate(semantic_ids):
        scores[msg_id] = scores.get(msg_id, 0.0) + 1.0 / (RRF_K + rank)
    for rank, msg_id in enumerate(keyword_ids):
        scores[msg_id] = scores.get(msg_id, 0.0) + 1.0 / (RRF_K + rank)

    ranked_ids = sorted(scores, key=lambda i: scores[i], reverse=True)

    results: list[Message] = []
    for msg_id in ranked_ids:
        msg = session.get(Message, msg_id)
        if msg is not None and _passes_filters(msg, filters):
            results.append(msg)
        if len(results) >= limit:
            break
    return results


def _semantic_search(collection: Collection, client: OpenAI, query: str, n: int) -> list[str]:
    if collection.count() == 0:
        return []
    query_embedding = embed_texts(client, [query])[0]
    results = collection.query(query_embeddings=[query_embedding], n_results=min(n, collection.count()))
    ids, distances = results["ids"][0], results["distances"][0]
    return [i for i, d in zip(ids, distances) if d <= settings.semantic_distance_threshold]


def _passes_filters(msg: Message, filters: SearchFilters) -> bool:
    if filters.category and msg.category != filters.category:
        return False
    if filters.sender_contains and filters.sender_contains.lower() not in msg.sender_email.lower():
        return False
    if filters.after and (msg.internal_date is None or msg.internal_date < filters.after):
        return False
    if filters.before and (msg.internal_date is None or msg.internal_date > filters.before):
        return False
    if filters.unread_only and not msg.is_unread:
        return False
    return True
