from dataclasses import replace

from chromadb.api.models.Collection import Collection
from openai import OpenAI
from sqlmodel import Session

from app.config import settings
from app.db.models import Message
from app.llm import INJECTION_GUARD
from app.query.understand import extract_query_filters
from app.retrieval.search import SearchFilters, hybrid_search, list_by_filters

RETRIEVAL_LIMIT = 15
LISTING_RETRIEVAL_LIMIT = 50
BODY_CHARS_FOR_ANSWERING = 2500
BODY_CHARS_FOR_LISTING = 400


def answer_question(session: Session, collection: Collection, client: OpenAI, question: str) -> dict:
    understood = extract_query_filters(client, question)

    if understood.is_listing_request and _has_filters(understood.filters):
        # "Give me a report of today's mail" wants everything in the window,
        # not the top-15-by-topical-relevance to a vague term like "report" —
        # that's what hybrid_search is for, and it's the wrong tool here.
        results = list_by_filters(session, understood.filters, limit=LISTING_RETRIEVAL_LIMIT)
        body_chars = BODY_CHARS_FOR_LISTING
    else:
        results = hybrid_search(
            session, collection, client, understood.search_terms, understood.filters, RETRIEVAL_LIMIT
        )
        if not results and _has_droppable_filters(understood.filters):
            # Only category/sender are LLM-guessed and worth retrying without —
            # never silently drop an explicit date range the user actually
            # asked for, or "report for today" can come back with last week's
            # mail because the date filter got quietly discarded.
            relaxed = replace(understood.filters, category=None, sender_contains=None)
            results = hybrid_search(session, collection, client, understood.search_terms, relaxed, RETRIEVAL_LIMIT)
        body_chars = BODY_CHARS_FOR_ANSWERING

    answer = _synthesize_answer(client, question, results, body_chars)
    return {"answer": answer, "sources": [_source(m) for m in results]}


def _has_filters(filters: SearchFilters) -> bool:
    return bool(filters.category or filters.sender_contains or filters.after or filters.before)


def _has_droppable_filters(filters: SearchFilters) -> bool:
    return bool(filters.category or filters.sender_contains)


def _synthesize_answer(client: OpenAI, question: str, messages: list[Message], body_chars: int) -> str:
    if not messages:
        context = "(No matching emails were found in the inbox for this question.)"
    else:
        context = "\n\n".join(
            f"--- Email {i + 1} ---\n"
            f"From: {m.sender_name} <{m.sender_email}>\n"
            f"Date: {m.internal_date.isoformat() if m.internal_date else 'unknown'}\n"
            f"Subject: {m.subject}\n"
            f"Category: {m.category or 'uncategorized'}\n\n"
            f"{m.body_text[:body_chars]}"
            for i, m in enumerate(messages)
        )

    system = (
        f"{INJECTION_GUARD}\n\n"
        "You are MailChef, a personal email assistant. Answer the user's "
        "question using ONLY the emails provided below. If they don't "
        "contain enough information to answer, say so plainly instead of "
        "guessing or using outside knowledge — in particular, if the emails "
        "list is empty or none of them fall in a date range the user asked "
        "about, say you found nothing there rather than substituting "
        "unrelated emails. Be concise. When useful, mention which sender and "
        "date an answer came from so the user can find the original email."
    )

    response = client.chat.completions.create(
        model=settings.answer_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Emails:\n\n{context}\n\nQuestion: {question}"},
        ],
    )
    return response.choices[0].message.content


def _source(m: Message) -> dict:
    return {
        "id": m.id,
        "from": f"{m.sender_name} <{m.sender_email}>",
        "subject": m.subject,
        "date": m.internal_date.isoformat() if m.internal_date else None,
    }
