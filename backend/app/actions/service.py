import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.actions.types import (
    ACTIONS_REQUIRING_LABEL,
    ActionType,
    requires_confirmation,
)
from app.config import settings
from app.db.models import Message, PendingAction
from app.gmail.client import GmailClient

MAX_BULK_ACTION_SIZE = 500


class ActionError(Exception):
    """Raised for user-fixable problems (bad ids, unknown label, expired
    proposal) — callers turn these into 400s, not 500s.
    """


def get_affected_messages(session: Session, message_ids: list[str]) -> list[Message]:
    if not message_ids:
        raise ActionError("No message ids given")
    if len(message_ids) > MAX_BULK_ACTION_SIZE:
        raise ActionError(
            f"{len(message_ids)} messages exceeds the {MAX_BULK_ACTION_SIZE}-message bulk action "
            "limit — narrow the search before proposing this action"
        )

    messages = []
    missing = []
    for msg_id in message_ids:
        msg = session.get(Message, msg_id)
        if msg is None:
            missing.append(msg_id)
        else:
            messages.append(msg)

    if missing:
        raise ActionError(f"Unknown message id(s), not found in local index: {missing}")
    return messages


def resolve_label_id(gmail_client: GmailClient, label_name: str) -> str:
    labels = gmail_client.list_labels()
    for label in labels:
        if label["id"] == label_name or label["name"].lower() == label_name.lower():
            return label["id"]
    available = ", ".join(sorted(l["name"] for l in labels))
    raise ActionError(f"No Gmail label matching {label_name!r}. Available labels: {available}")


def create_pending_action(
    session: Session,
    gmail_client: GmailClient,
    action: ActionType,
    message_ids: list[str],
    label_name: str | None = None,
) -> tuple[PendingAction, list[Message]]:
    messages = get_affected_messages(session, message_ids)

    label_id = None
    if action in ACTIONS_REQUIRING_LABEL:
        if not label_name:
            raise ActionError(f"{action} requires a label_name")
        label_id = resolve_label_id(gmail_client, label_name)

    pending = PendingAction(
        id=uuid.uuid4().hex,
        action=action.value,
        message_ids=",".join(message_ids),
        label_id=label_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.action_confirmation_ttl_minutes),
    )
    session.add(pending)
    session.commit()
    session.refresh(pending)
    return pending, messages


def get_pending_action(session: Session, proposal_id: str) -> PendingAction | None:
    return session.get(PendingAction, proposal_id)


def cancel_pending_action(session: Session, proposal_id: str) -> bool:
    pending = session.get(PendingAction, proposal_id)
    if pending is None or pending.executed:
        return False
    session.delete(pending)
    session.commit()
    return True


def confirm_pending_action(session: Session, gmail_client: GmailClient, proposal_id: str) -> dict:
    pending = session.get(PendingAction, proposal_id)
    if pending is None:
        raise ActionError("No such proposed action — it may have already been confirmed or cancelled")
    if pending.executed:
        raise ActionError("This action was already executed")
    if datetime.now(timezone.utc) > pending.expires_at.replace(tzinfo=timezone.utc):
        raise ActionError("This proposed action expired — propose it again to get a fresh confirmation")

    action = ActionType(pending.action)
    message_ids = pending.message_ids.split(",")
    messages = get_affected_messages(session, message_ids)

    for msg in messages:
        _apply_action(gmail_client, action, msg.id, pending.label_id)
        _update_local_state(session, action, msg, pending.label_id)

    pending.executed = True
    pending.executed_at = datetime.now(timezone.utc)
    session.add(pending)
    session.commit()

    return {"action": action.value, "message_count": len(messages), "message_ids": message_ids}


def execute_immediate(
    session: Session,
    gmail_client: GmailClient,
    action: ActionType,
    message_ids: list[str],
    label_name: str | None = None,
) -> dict:
    """For safe, single-target, reversible actions only. Anything destructive
    or bulk must go through create_pending_action + confirm_pending_action.
    """
    if requires_confirmation(action, len(message_ids)):
        raise ActionError(
            f"{action} on {len(message_ids)} message(s) requires confirmation — "
            "use /actions/propose then /actions/confirm"
        )

    messages = get_affected_messages(session, message_ids)

    label_id = None
    if action in ACTIONS_REQUIRING_LABEL:
        if not label_name:
            raise ActionError(f"{action} requires a label_name")
        label_id = resolve_label_id(gmail_client, label_name)

    for msg in messages:
        _apply_action(gmail_client, action, msg.id, label_id)
        _update_local_state(session, action, msg, label_id)
    session.commit()

    return {"action": action.value, "message_count": len(messages), "message_ids": message_ids}


def _apply_action(gmail_client: GmailClient, action: ActionType, message_id: str, label_id: str | None) -> None:
    if action == ActionType.MARK_READ:
        gmail_client.modify_labels(message_id, remove=["UNREAD"])
    elif action == ActionType.MARK_UNREAD:
        gmail_client.modify_labels(message_id, add=["UNREAD"])
    elif action == ActionType.ARCHIVE:
        gmail_client.modify_labels(message_id, remove=["INBOX"])
    elif action == ActionType.STAR:
        gmail_client.modify_labels(message_id, add=["STARRED"])
    elif action == ActionType.UNSTAR:
        gmail_client.modify_labels(message_id, remove=["STARRED"])
    elif action == ActionType.ADD_LABEL:
        gmail_client.modify_labels(message_id, add=[label_id])
    elif action == ActionType.REMOVE_LABEL:
        gmail_client.modify_labels(message_id, remove=[label_id])
    elif action == ActionType.TRASH:
        gmail_client.trash_message(message_id)


def _update_local_state(session: Session, action: ActionType, message: Message, label_id: str | None) -> None:
    """Keeps the local index in sync without waiting for the next Gmail
    sync — so a subsequent /search or digest reflects the change immediately.
    """
    labels = set(message.label_ids.split(",")) if message.label_ids else set()

    if action == ActionType.MARK_READ:
        labels.discard("UNREAD")
        message.is_unread = False
    elif action == ActionType.MARK_UNREAD:
        labels.add("UNREAD")
        message.is_unread = True
    elif action == ActionType.ARCHIVE:
        labels.discard("INBOX")
    elif action == ActionType.STAR:
        labels.add("STARRED")
    elif action == ActionType.UNSTAR:
        labels.discard("STARRED")
    elif action == ActionType.ADD_LABEL and label_id:
        labels.add(label_id)
    elif action == ActionType.REMOVE_LABEL and label_id:
        labels.discard(label_id)
    elif action == ActionType.TRASH:
        labels.discard("INBOX")
        labels.add("TRASH")

    message.label_ids = ",".join(sorted(labels))
    message.updated_at = datetime.now(timezone.utc)
    session.add(message)
