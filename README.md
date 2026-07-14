# MailChef

A personal email assistant that connects to your Gmail account and lets you
query and manage your inbox through natural language.

## Architecture

- **Backend** (`backend/`): FastAPI service deployed on Fly.io. Owns Gmail
  OAuth, message sync, the vector store, classification, query answering,
  inbox actions, and the scheduled digest. Also serves the built web UI as
  static files (see `web/`) at the same origin.
- **CLI** (`cli/`): thin client that talks to the backend over HTTPS with a
  bearer token.
- **Web UI** (`web/`): React + TypeScript SPA, same API and bearer-token
  model as the CLI (paste the token once, stored in the browser). Built
  with Vite; the production build is served directly by the FastAPI backend
  (no separate hosting/CORS setup) — see the multi-stage `backend/Dockerfile`.
- **Storage**: SQLite (message metadata, sync state, encrypted OAuth token,
  digest history) + Chroma (embeddings for semantic search), both on a
  persistent Fly volume.
- **LLM**: two-tier OpenAI usage — a cheap/fast model for bulk classification
  and screening, a stronger model for summaries and complex query answering.

## Status

All planned stages are built and verified against a real Gmail account,
including a real containerized (Docker) build of backend + frontend. See
[docs/SETUP.md](docs/SETUP.md) for setup instructions (Google OAuth client,
secrets, local run, Fly.io deploy, and usage examples for every stage).

- [x] Stage (a): Gmail OAuth2 auth + message sync
- [x] Stage (b): Classification + retrieval (embeddings + Chroma + FTS keyword search)
- [x] Stage (c): Query answering (RAG)
- [x] Stage (d): Inbox actions with confirmation
- [x] Stage (e): Scheduled morning digest
- [x] CLI client
- [x] Web UI (React SPA served by the backend)

## Quick start (after setup)

```bash
mailchef configure          # one-time: backend URL + API token
mailchef sync                # pull mail from Gmail
mailchef classify && mailchef index   # categorize + embed it
mailchef ask "Any interview schedules this week?"
mailchef digest --now       # generate today's digest on demand
mailchef chat                # interactive REPL: plain text = ask, /digest /search /archive ... = actions
```

Or open the web UI at your backend's URL (e.g. `http://localhost:8080`) and paste the same API token when prompted.

## Security notes

- Gmail tokens are encrypted at rest (Fernet) and never hardcoded — see
  `backend/.env.example`.
- The agent never treats content inside email bodies as instructions, only
  as data to answer questions about. Only your direct commands to the CLI
  are treated as instructions.
- Destructive or irreversible actions (archive, trash, bulk operations)
  always show the affected emails and require explicit confirmation first.
