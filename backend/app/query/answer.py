from chromadb.api.models.Collection import Collection
from openai import OpenAI
from sqlmodel import Session

from app.config import settings
from app.db.models import Message
from app.llm import INJECTION_GUARD
from app.query.understand import extract_query_filters
from app.retrieval.search import hybrid_search

RETRIEVAL_LIMIT = 15
BODY_CHARS_FOR_ANSWERING = 2500


def answer_question(session: Session, collection: Collection, client: OpenAI, question: str) -> dict:
    understood = extract_query_filters(client, question)

    results = hybrid_search(
        session, collection, client, understood.search_terms, understood.filters, RETRIEVAL_LIMIT
    )
    if not results and _has_filters(understood.filters):
        # The extracted filters may be wrong (e.g. a misread date range) —
        # retry unfiltered so a bad filter can't produce a false "nothing
        # found" instead of an actual answer.
        results = hybrid_search(session, collection, client, understood.search_terms, limit=RETRIEVAL_LIMIT)

    answer = _synthesize_answer(client, question, results)
    return {"answer": answer, "sources": [_source(m) for m in results]}


def _has_filters(filters) -> bool:
    return bool(filters.category or filters.sender_contains or filters.after or filters.before)


def _synthesize_answer(client: OpenAI, question: str, messages: list[Message]) -> str:
    if not messages:
        context = "(No matching emails were found in the inbox for this question.)"
    else:
        context = "\n\n".join(
            f"--- Email {i + 1} ---\n"
            f"From: {m.sender_name} <{m.sender_email}>\n"
            f"Date: {m.internal_date.isoformat() if m.internal_date else 'unknown'}\n"
            f"Subject: {m.subject}\n"
            f"Category: {m.category or 'uncategorized'}\n\n"
            f"{m.body_text[:BODY_CHARS_FOR_ANSWERING]}"
            for i, m in enumerate(messages)
        )

    system = (
        f"{INJECTION_GUARD}\n\n"
        "You are MailChef, a personal email assistant. Answer the user's "
        "question using ONLY the emails provided below. If they don't "
        "contain enough information to answer, say so plainly instead of "
        "guessing or using outside knowledge. Be concise. When useful, "
        "mention which sender and date an answer came from so the user can "
        "find the original email."
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
