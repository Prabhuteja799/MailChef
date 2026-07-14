from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.db.models import JobApplication

RECENT_DAYS = 7

# Named individually — genuinely actionable, and rare enough not to flood
# the digest.
ITEMIZED_STATUSES = ["interview", "moving_forward", "offer"]
# Rejections can run into the dozens per week for an active job search;
# itemizing each one would bury the interview/offer signal exactly the way
# the old Jobs board did. Just count them.
COUNTED_STATUSES = ["rejected"]

STATUS_HEADINGS = {
    "interview": "New interviews",
    "moving_forward": "Moving forward",
    "offer": "Offers",
}


def get_job_highlights(session: Session) -> dict:
    """Structured recent-movement data, shared by the JSON API response
    (web UI renders it as colored cards) and render_job_pipeline_markdown
    (CLI/markdown rendering).
    """
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = session.exec(
        select(JobApplication)
        .where(JobApplication.status_updated_at >= since)
        .where(JobApplication.status.in_(ITEMIZED_STATUSES + COUNTED_STATUSES))
        .order_by(JobApplication.status_updated_at.desc())
    ).all()

    by_status: dict[str, list[JobApplication]] = defaultdict(list)
    for application in recent:
        by_status[application.status].append(application)

    return {
        "interview": [_app_summary(a) for a in by_status.get("interview", [])],
        "moving_forward": [_app_summary(a) for a in by_status.get("moving_forward", [])],
        "offer": [_app_summary(a) for a in by_status.get("offer", [])],
        "rejected_count": len(by_status.get("rejected", [])),
    }


def _app_summary(a: JobApplication) -> dict:
    return {
        "id": a.id,
        "company": a.company,
        "role": a.role,
        "status_updated_at": a.status_updated_at.isoformat(),
    }


def render_job_pipeline_markdown(highlights: dict) -> str:
    if not any(highlights[s] for s in ITEMIZED_STATUSES) and not highlights["rejected_count"]:
        return ""

    lines = [f"\n## Job search pipeline (last {RECENT_DAYS} days)"]
    for status in ITEMIZED_STATUSES:
        applications = highlights[status]
        if not applications:
            continue
        lines.append(f"\n**{STATUS_HEADINGS[status]}:**")
        for a in applications:
            role = f" — {a['role']}" if a["role"] else ""
            lines.append(f"- {a['company']}{role} _(updated {a['status_updated_at'][:10]})_")

    if highlights["rejected_count"]:
        lines.append(f"\n{highlights['rejected_count']} rejection(s) this week.")

    return "\n".join(lines)
