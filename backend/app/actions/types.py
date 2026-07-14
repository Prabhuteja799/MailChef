from enum import StrEnum


class ActionType(StrEnum):
    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    ARCHIVE = "archive"
    STAR = "star"
    UNSTAR = "unstar"
    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"
    TRASH = "trash"


# Irreversible-enough-to-matter, or wide-blast-radius: always require the
# propose -> show affected emails -> confirm flow, never immediate execution.
CONFIRMATION_REQUIRED_ACTIONS = {ActionType.ARCHIVE, ActionType.TRASH}

ACTIONS_REQUIRING_LABEL = {ActionType.ADD_LABEL, ActionType.REMOVE_LABEL}


def requires_confirmation(action: ActionType, message_count: int) -> bool:
    return action in CONFIRMATION_REQUIRED_ACTIONS or message_count > 1
