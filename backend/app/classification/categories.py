import json
from pathlib import Path

from pydantic import BaseModel

from app.config import settings

_BUNDLED_DEFAULT_PATH = Path(__file__).parent / "categories.json"

# Always available regardless of config, used when the classifier can't
# confidently place a message into one of the configured categories.
UNCATEGORIZED = "uncategorized"


class Category(BaseModel):
    name: str
    description: str


def categories_config_path() -> Path:
    """Drop a categories.json onto the Fly volume's data dir to override the
    bundled defaults without rebuilding the image.
    """
    override = settings.data_dir / "categories.json"
    return override if override.exists() else _BUNDLED_DEFAULT_PATH


def load_categories() -> list[Category]:
    raw = json.loads(categories_config_path().read_text())
    return [Category(**c) for c in raw]
