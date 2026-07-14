import chromadb
from chromadb.api.models.Collection import Collection

from app.config import settings

COLLECTION_NAME = "mailchef_messages"

_client: chromadb.ClientAPI | None = None


def get_chroma_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(settings.chroma_path))
    return _client


def get_collection() -> Collection:
    # Cosine distance (bounded [0, 2]) makes the similarity threshold in
    # search.py meaningful; Chroma's default (L2) doesn't have a fixed range.
    return get_chroma_client().get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )
