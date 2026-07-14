import json
from datetime import datetime

from openai import OpenAI
from sqlmodel import Session, select

from app.classification.categories import UNCATEGORIZED, Category, load_categories
from app.config import settings
from app.db.models import Message
from app.llm import INJECTION_GUARD
from app.util import chunks

BATCH_SIZE = 25
SNIPPET_CHARS = 300


def classify_pending_messages(
    session: Session, client: OpenAI, limit: int = 1000, since: datetime | None = None
) -> dict:
    categories = load_categories()
    query = select(Message).where(Message.category.is_(None))
    if since is not None:
        query = query.where(Message.internal_date >= since)
    pending = session.exec(query.limit(limit)).all()

    classified = 0
    for batch in chunks(pending, BATCH_SIZE):
        assignments = _classify_batch(client, batch, categories)
        for msg in batch:
            msg.category = assignments.get(msg.id, UNCATEGORIZED)
            session.add(msg)
        session.commit()
        classified += len(batch)

    return {"classified": classified, "categories": [c.name for c in categories]}


def _classify_batch(client: OpenAI, batch: list[Message], categories: list[Category]) -> dict[str, str]:
    category_names = [c.name for c in categories]
    category_lines = "\n".join(f"- {c.name}: {c.description}" for c in categories)

    emails_block = "\n\n".join(
        f"id: {m.id}\nfrom: {m.sender_name} <{m.sender_email}>\nsubject: {m.subject}\n"
        f"snippet: {m.snippet[:SNIPPET_CHARS]}"
        for m in batch
    )

    system = (
        f"{INJECTION_GUARD}\n\n"
        "You classify emails into exactly one category each, based only on "
        "sender, subject, and snippet. Categories:\n"
        f"{category_lines}\n\n"
        "Return one classification per email id given, using only the "
        "category names listed above."
    )

    schema = {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string", "enum": category_names},
                    },
                    "required": ["id", "category"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classifications"],
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
            "json_schema": {"name": "email_classifications", "strict": True, "schema": schema},
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    valid_ids = {m.id for m in batch}
    return {
        item["id"]: item["category"]
        for item in parsed["classifications"]
        if item["id"] in valid_ids and item["category"] in category_names
    }
