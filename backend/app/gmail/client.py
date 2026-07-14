import base64
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

_WHITESPACE_RE = re.compile(r"[ \t]+")

# Marketing/ATS email HTML is often malformed (unclosed tags, MSO conditional
# comments, deeply nested tables) — regex tag-stripping can't reliably tell
# "inside a <style> block" from "inside the message", which is exactly what
# leaked raw CSS into extracted bodies before. A real parser handles this
# properly regardless of how messy the markup is.
_SKIP_TAGS = {"style", "script", "head"}
_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


@dataclass
class ParsedMessage:
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    to_recipients: str
    subject: str
    snippet: str
    body_text: str
    internal_date: datetime
    label_ids: list[str] = field(default_factory=list)

    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.label_ids


class GmailClient:
    def __init__(self, credentials: Credentials):
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def get_profile(self) -> dict:
        return self._service.users().getProfile(userId="me").execute()

    def list_message_ids(
        self, query: str | None = None, page_token: str | None = None, max_results: int = 100
    ) -> tuple[list[str], str | None]:
        resp = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, pageToken=page_token, maxResults=max_results)
            .execute()
        )
        ids = [m["id"] for m in resp.get("messages", [])]
        return ids, resp.get("nextPageToken")

    def get_message(self, message_id: str) -> ParsedMessage:
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return _parse_message(raw)

    def list_history(
        self, start_history_id: str, page_token: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Returns (history records, next_page_token). Raises HttpError 404 if
        start_history_id is too old — callers should fall back to a full resync.
        """
        resp = (
            self._service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=start_history_id,
                pageToken=page_token,
                historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
            )
            .execute()
        )
        return resp.get("history", []), resp.get("nextPageToken")

    # --- inbox actions (stage d wires these up behind a confirmation flow) ---

    def modify_labels(self, message_id: str, add: list[str] | None = None, remove: list[str] | None = None) -> None:
        self._service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": add or [], "removeLabelIds": remove or []},
        ).execute()

    def trash_message(self, message_id: str) -> None:
        self._service.users().messages().trash(userId="me", id=message_id).execute()

    def list_labels(self) -> list[dict]:
        resp = self._service.users().labels().list(userId="me").execute()
        return resp.get("labels", [])


def _parse_message(raw: dict) -> ParsedMessage:
    headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    internal_date = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=timezone.utc)

    return ParsedMessage(
        id=raw["id"],
        thread_id=raw["threadId"],
        sender_name=sender_name,
        sender_email=sender_email,
        to_recipients=headers.get("to", ""),
        subject=headers.get("subject", "(no subject)"),
        snippet=raw.get("snippet", ""),
        body_text=_extract_body_text(raw.get("payload", {})),
        internal_date=internal_date,
        label_ids=raw.get("labelIds", []),
    )


def _extract_body_text(payload: dict) -> str:
    """Walks the MIME tree, preferring text/plain and falling back to a
    tag-stripped text/html part.
    """
    plain, html = _find_body_parts(payload)
    if plain:
        return plain
    if html:
        return _html_to_text(html)
    return ""


def _html_to_text(html: str) -> str:
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        # Malformed enough to choke the parser — fall back to whatever was
        # extracted before the failure rather than losing the message.
        pass
    unescaped = unescape(extractor.text())

    # Tag-stripped email templates leave many near-empty lines (one per
    # empty table cell/div) — collapse per-line whitespace and drop blanks
    # rather than just capping consecutive blank lines.
    lines = (_WHITESPACE_RE.sub(" ", line).strip() for line in unescaped.splitlines())
    return "\n".join(line for line in lines if line).strip()


def _find_body_parts(payload: dict) -> tuple[str | None, str | None]:
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return _decode(body_data), None
    if mime_type == "text/html" and body_data:
        return None, _decode(body_data)

    plain, html = None, None
    for part in payload.get("parts", []):
        p_plain, p_html = _find_body_parts(part)
        plain = plain or p_plain
        html = html or p_html
    return plain, html


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
