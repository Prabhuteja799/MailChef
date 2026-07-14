from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_client_id: str
    google_client_secret: str
    google_oauth_redirect_uri: str

    token_encryption_key: str
    mailchef_api_token: str

    openai_api_key: str
    classifier_model: str = "gpt-4o-mini"
    answer_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    # Cosine-distance cutoff for semantic search (0 = identical, 2 = opposite).
    # Chroma always returns its nearest neighbors regardless of how similar
    # they actually are, so without this cutoff an unrelated query would
    # still retrieve "closest" emails and risk grounding an answer in them.
    # This value is a reasonable starting point, not an empirically tuned
    # one — adjust it after watching real /search results.
    semantic_distance_threshold: float = 0.45

    mailchef_data_dir: str = "./data"
    initial_sync_days: int = 30

    action_confirmation_ttl_minutes: int = 10

    digest_hour: int = 7
    digest_minute: int = 30
    digest_timezone: str = "America/Los_Angeles"

    @property
    def data_dir(self) -> Path:
        path = Path(self.mailchef_data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "mailchef.db"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"


settings = Settings()
