from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OAuthToken(SQLModel, table=True):
    """Single-row table: this is a personal, single-user assistant."""

    id: int | None = Field(default=None, primary_key=True)
    provider: str = "gmail"
    refresh_token_encrypted: str
    access_token_encrypted: str | None = None
    token_expiry: datetime | None = None
    scopes: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class SyncState(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    last_history_id: str | None = None
    last_synced_at: datetime | None = None


class Message(SQLModel, table=True):
    id: str = Field(primary_key=True)  # Gmail message id
    thread_id: str
    sender_name: str = ""
    sender_email: str = ""
    to_recipients: str = ""
    subject: str = ""
    snippet: str = ""
    body_text: str = ""
    internal_date: datetime | None = None
    label_ids: str = ""  # comma-separated Gmail label IDs
    is_unread: bool = False
    category: str | None = None  # filled in by the classifier (stage b)
    indexed_at: datetime | None = None  # set once embedded into the vector store
    updated_at: datetime = Field(default_factory=utcnow)


class PendingAction(SQLModel, table=True):
    """A proposed inbox action awaiting explicit user confirmation. Created
    by POST /actions/propose, only takes effect via POST /actions/confirm —
    this is what makes destructive/bulk actions "show me the affected
    emails and require confirmation" rather than fire-and-forget.
    """

    id: str = Field(primary_key=True)  # uuid4 hex
    action: str
    message_ids: str  # comma-separated Gmail message ids
    label_id: str | None = None  # resolved Gmail label id, for add_label/remove_label
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    executed: bool = False
    executed_at: datetime | None = None


class Digest(SQLModel, table=True):
    id: str = Field(primary_key=True)  # uuid4 hex
    generated_at: datetime = Field(default_factory=utcnow)
    content_markdown: str
    unread_count: int
    category_counts_json: str = "{}"
