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
    is_listing_request: bool


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
        f"({now.strftime('%A')}), current time {now.strftime('%H:%M')}. "
        "Resolve relative dates (\"this week\", \"today\", \"last month\", "
        "\"last 48 hours\") into absolute YYYY-MM-DD dates using that as "
        "\"today\". For hour-based windows (e.g. \"last 48 hours\"), round "
        "after_date DOWN (earlier) by one extra day rather than under-covering "
        "the window. Leave after_date/before_date empty (\"\") if the "
        "question has no date scope. Leave sender_hint empty if no specific "
        "person or company is named. Use category \"none\" unless the "
        f"question clearly maps to one of these:\n{category_lines}\n\n"
        "Set is_listing_request true if the user wants a broad listing/report/"
        "summary of matching emails (\"give me a report\", \"what did I get "
        "today\", \"summarize this week\"), false for a specific factual "
        "question (\"did X reply\", \"when is my interview\")."
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
            "is_listing_request": {"type": "boolean"},
        },
        "required": [
            "search_terms", "category", "sender_hint", "after_date", "before_date", "is_listing_request",
        ],
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
    return UnderstoodQuery(
        search_terms=parsed["search_terms"] or question,
        filters=filters,
        is_listing_request=parsed["is_listing_request"],
    )


def _safe_parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except (ValueError, OverflowError):
        return None
