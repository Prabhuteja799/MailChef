from enum import StrEnum


class EventType(StrEnum):
    APPLIED = "applied"
    ACKNOWLEDGED = "acknowledged"
    INTERVIEW = "interview"
    MOVING_FORWARD = "moving_forward"
    OFFER = "offer"
    REJECTED = "rejected"
    OTHER = "other"


# Human-readable labels for the web UI / CLI table.
STATUS_LABELS = {
    EventType.APPLIED: "Applied",
    EventType.ACKNOWLEDGED: "Acknowledged",
    EventType.INTERVIEW: "Interview",
    EventType.MOVING_FORWARD: "Moving forward",
    EventType.OFFER: "Offer",
    EventType.REJECTED: "Rejected",
    EventType.OTHER: "Other",
}
