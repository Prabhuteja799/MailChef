from openai import OpenAI

from app.config import settings
from app.util import chunks

EMBED_BATCH_SIZE = 100


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for batch in chunks(texts, EMBED_BATCH_SIZE):
        response = client.embeddings.create(model=settings.embedding_model, input=list(batch))
        vectors.extend(d.embedding for d in response.data)
    return vectors
