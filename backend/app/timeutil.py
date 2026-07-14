from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings


def local_now() -> datetime:
    return datetime.now(ZoneInfo(settings.digest_timezone))
