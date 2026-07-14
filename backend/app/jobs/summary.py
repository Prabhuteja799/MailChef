from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.db.models import JobApplication

RECENT_DAYS = 7

# applied/acknowledged/other are too noisy for a digest highlight — only
# call out genuine movement.
HIGHLIGHT_STATUSES = ["interview", "moving_forward", "offer", "rejected"]
STATUS_HEADINGS = {
    "interview": "New interviews",
    "moving_forward": "Moving forward",
    "offer": "Offers",
    "rejected": "Rejected",
}


def render_job_pipeline_section(session: Session) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = session.exec(
        select(JobApplication)
        .where(JobApplication.status_updated_at >= since)
        .where(JobApplication.status.in_(HIGHLIGHT_STATUSES))
        .order_by(JobApplication.status_updated_at.desc())
    ).all()

    if not recent:
        return ""

    by_status: dict[str, list[JobApplication]] = defaultdict(list)
    for application in recent:
        by_status[application.status].append(application)

    lines = [f"\n## Job search pipeline (last {RECENT_DAYS} days)"]
    for status in HIGHLIGHT_STATUSES:
        applications = by_status.get(status)
        if not applications:
            continue
        lines.append(f"\n**{STATUS_HEADINGS[status]}:**")
        for a in applications:
            role = f" — {a.role}" if a.role else ""
            lines.append(f"- {a.company}{role} _(updated {a.status_updated_at.date().isoformat()})_")

    return "\n".join(lines)
