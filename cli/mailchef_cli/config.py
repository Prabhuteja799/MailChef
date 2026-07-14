import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".mailchef"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class CLIConfig:
    backend_url: str
    api_token: str


def load_config() -> CLIConfig:
    backend_url = os.environ.get("MAILCHEF_BACKEND_URL")
    api_token = os.environ.get("MAILCHEF_API_TOKEN")

    if CONFIG_PATH.exists():
        data = json.loads(CONFIG_PATH.read_text())
        backend_url = backend_url or data.get("backend_url")
        api_token = api_token or data.get("api_token")

    if not backend_url or not api_token:
        raise RuntimeError(
            "MailChef isn't configured yet. Run `mailchef configure`, or set "
            "MAILCHEF_BACKEND_URL and MAILCHEF_API_TOKEN in your environment."
        )
    return CLIConfig(backend_url.rstrip("/"), api_token)


def save_config(backend_url: str, api_token: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"backend_url": backend_url.rstrip("/"), "api_token": api_token}, indent=2))
    CONFIG_PATH.chmod(0o600)
