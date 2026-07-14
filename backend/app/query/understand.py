import json
from dataclasses import dataclass
from datetime import datetime

from dateutil import parser as date_parser
from openai import OpenAI

from app.classification.categories import load_categories
from app.config import settings
from app.retrieval.search import SearchFilters
from app.timeutil import local_now

NO_CATEGORY = "none"


@dataclass
class UnderstoodQuery:
    search_terms: str
    filters: SearchFilters


def extract_query_filters(client: OpenAI, question: str) -> UnderstoodQuery:
    """Turns a natural-language question into search terms + structured
    filters (category, sender, date range), resolving relative dates like
    "this week" against the user's configured timezone. Uses the cheap tier —
    this is a cheap classification-shaped task, not the final answer.
    """
    categories = load_categories()
    category_names = [c.name for c in categories]
    now = local_now()

    category_lines = "\n".join(f"- {c.name}: {c.description}" for c in categories)
    system = (
        "You turn a natural-language question about someone's email inbox "
        f"into search parameters. Today is {now.date().isoformat()} "
        f"({now.strftime('%A')}). Resolve relative dates (\"this week\", "
        "\"today\", \"last month\") into absolute YYYY-MM-DD dates using that "
        "as \"today\". Leave after_date/before_date empty (\"\") if the "
        "question has no date scope. Leave sender_hint empty if no specific "
        "person or company is named. Use category \"none\" unless the "
        f"question clearly maps to one of these:\n{category_lines}"
    )

    schema = {
        "type": "object",
        "properties": {
            "search_terms": {
                "type": "string",
                "description": "Core keywords/topic to search for, distilled from the question.",
            },
            "category": {"type": "string", "enum": [*category_names, NO_CATEGORY]},
            "sender_hint": {"type": "string"},
            "after_date": {"type": "string"},
            "before_date": {"type": "string"},
        },
        "required": ["search_terms", "category", "sender_hint", "after_date", "before_date"],
        "additionalProperties": False,
    }

    response = client.chat.completions.create(
        model=settings.classifier_model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "query_filters", "strict": True, "schema": schema},
        },
    )

    parsed = json.loads(response.choices[0].message.content)
    filters = SearchFilters(
        category=parsed["category"] if parsed["category"] != NO_CATEGORY else None,
        sender_contains=parsed["sender_hint"] or None,
        after=_safe_parse_date(parsed["after_date"]),
        before=_safe_parse_date(parsed["before_date"]),
    )
    return UnderstoodQuery(search_terms=parsed["search_terms"] or question, filters=filters)


def _safe_parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except (ValueError, OverflowError):
        return None
