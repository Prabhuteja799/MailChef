import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from openai import OpenAI
from sqlmodel import Session, select

from app.classification.categories import UNCATEGORIZED
from app.config import settings
from app.db.models import Digest, Message
from app.jobs.summary import render_job_pipeline_section
from app.llm import INJECTION_GUARD

MAX_EMAILS_PER_CATEGORY = 15
BODY_CHARS_FOR_DIGEST = 1200

_SCHEMA = {
    "type": "object",
    "properties": {
        "category_summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["category", "summary"],
                "additionalProperties": False,
            },
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "source_email_id": {"type": "string"},
                },
                "required": ["summary", "source_email_id"],
                "additionalProperties": False,
            },
        },
        "interview_schedule": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "when": {"type": "string", "description": "Date/time as stated or implied in the email"},
                    "source_email_id": {"type": "string"},
                },
                "required": ["summary", "when", "source_email_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["category_summaries", "action_items", "interview_schedule"],
    "additionalProperties": False,
}


def generate_digest(session: Session, client: OpenAI) -> Digest:
    unread = session.exec(
        select(Message).where(Message.is_unread == True).order_by(Message.internal_date.desc())  # noqa: E712
    ).all()

    # A DB query, not an LLM call — cheap enough to always include, and
    # meaningful even on an empty inbox (rejections/interviews don't
    # require the email to still be unread).
    job_section = render_job_pipeline_section(session)

    if not unread:
        markdown = "# MailChef Morning Digest\n\nNo unread mail — inbox zero." + job_section
        return _save_digest(session, markdown, 0, {})

    grouped: dict[str, list[Message]] = defaultdict(list)
    for m in unread:
        grouped[m.category or UNCATEGORIZED].append(m)
    category_counts = {cat: len(msgs) for cat, msgs in grouped.items()}

    parsed = _summarize_with_llm(client, grouped)
    markdown = _render_markdown(len(unread), category_counts, parsed) + job_section
    return _save_digest(session, markdown, len(unread), category_counts)


def _summarize_with_llm(client: OpenAI, grouped: dict[str, list[Message]]) -> dict:
    blocks = []
    for category, messages in grouped.items():
        subset = messages[:MAX_EMAILS_PER_CATEGORY]
        omitted = len(messages) - len(subset)
        header = f"## Category: {category} ({len(messages)} unread"
        header += f", showing {len(subset)})" if omitted else ")"
        entries = "\n".join(
            f"- id={m.id} | {m.internal_date.isoformat() if m.internal_date else 'unknown date'} | "
            f"From: {m.sender_name} <{m.sender_email}> | Subject: {m.subject}\n"
            f"  {m.body_text[:BODY_CHARS_FOR_DIGEST]}"
            for m in subset
        )
        blocks.append(f"{header}\n{entries}")
    context = "\n\n".join(blocks)

    system = (
        f"{INJECTION_GUARD}\n\n"
        "You are MailChef, generating a morning inbox digest from the unread "
        "emails below, grouped by category. For each category with mail, "
        "write a concise 1-3 sentence summary. Separately list concrete "
        "action items — emails that need a reply or some action from the "
        "user — and any interview or meeting schedule entries with their "
        "date/time, each referencing the source email's id. Only use what's "
        "actually in the emails provided; don't invent dates or details."
    )

    response = client.chat.completions.create(
        model=settings.answer_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ],
        response_format={"type": "json_schema", "json_schema": {"name": "digest", "strict": True, "schema": _SCHEMA}},
    )
    return json.loads(response.choices[0].message.content)


def _render_markdown(unread_total: int, category_counts: dict[str, int], parsed: dict) -> str:
    lines = ["# MailChef Morning Digest", f"\n{unread_total} unread email(s)\n", "## By category"]
    for category, count in sorted(category_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {category}: {count}")

    if parsed["interview_schedule"]:
        lines.append("\n## Interview / meeting schedule")
        for item in parsed["interview_schedule"]:
            lines.append(f"- **{item['when']}** — {item['summary']} _(email {item['source_email_id']})_")

    if parsed["action_items"]:
        lines.append("\n## Action items / needs a reply")
        for item in parsed["action_items"]:
            lines.append(f"- {item['summary']} _(email {item['source_email_id']})_")

    if parsed["category_summaries"]:
        lines.append("\n## Summaries")
        for item in parsed["category_summaries"]:
            lines.append(f"\n**{item['category']}**: {item['summary']}")

    return "\n".join(lines)


def _save_digest(session: Session, markdown: str, unread_count: int, category_counts: dict[str, int]) -> Digest:
    digest = Digest(
        id=uuid.uuid4().hex,
        generated_at=datetime.now(timezone.utc),
        content_markdown=markdown,
        unread_count=unread_count,
        category_counts_json=json.dumps(category_counts),
    )
    session.add(digest)
    session.commit()
    session.refresh(digest)
    return digest
