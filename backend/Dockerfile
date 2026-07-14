# Build context is the repo root (see fly.toml: context = ".."), so this
# stage can reach both backend/ and web/.

FROM node:22-slim AS frontend-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
COPY backend/app ./app

RUN pip install --no-cache-dir .

# app/main.py resolves the frontend at ../../web/dist relative to itself —
# three parents up from /app/app/main.py is /, so it lands here.
COPY --from=frontend-build /web/dist /web/dist

# Persistent volume mount point: SQLite DB + Chroma vector store live here
VOLUME ["/data"]
ENV MAILCHEF_DATA_DIR=/data

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
