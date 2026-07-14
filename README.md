# MailChef

A personal email assistant that connects to your Gmail account and lets you
query and manage your inbox through natural language — with a CLI, a web UI,
and a job-application tracker built on top of the same retrieval layer.

**Getting started:** [docs/SETUP.md](docs/SETUP.md) covers Google OAuth setup,
secrets, running locally, deploying to Fly.io, and usage examples for every
feature below.

## Architecture

- **Backend** (`backend/`): FastAPI service. Owns Gmail OAuth, message sync,
  the vector store, classification, query answering, inbox actions, the
  scheduled digest, and job-application tracking. Also serves the built web
  UI as static files (see `web/`) at the same origin.
- **CLI** (`cli/`): thin client that talks to the backend over HTTPS with a
  bearer token. See [docs/SETUP.md §10](docs/SETUP.md) for install + commands.
- **Web UI** (`web/`): React + TypeScript SPA, same API and bearer-token
  model as the CLI (paste the token once, stored in the browser). Built
  with Vite; the production build is served directly by the FastAPI backend
  (no separate hosting/CORS setup) — see the multi-stage `backend/Dockerfile`.
- **Storage**: SQLite (message metadata, sync state, encrypted OAuth token,
  digest history, tracked job applications) + Chroma (embeddings for semantic
  search), both on a persistent volume. Schema changes auto-migrate additively
  on startup — see `backend/app/db/database.py`.
- **LLM**: two-tier OpenAI usage — a cheap/fast model for bulk classification,
  job-event extraction, and screening; a stronger model for summaries and
  complex query answering.

## Status

All planned stages are built and verified against a real Gmail account,
including a real containerized (Docker) build of backend + frontend, and a
live deployment to Fly.io.

- [x] Gmail OAuth2 auth + message sync
- [x] Classification + retrieval (embeddings + Chroma + FTS keyword search)
- [x] Query answering (RAG)
- [x] Inbox actions with confirmation
- [x] Scheduled morning digest
- [x] Job application tracker (interview/reply/rejection extraction, matched
      to a per-company status, surfaced in the digest, CLI, and web UI)
- [x] CLI client
- [x] Web UI (React SPA served by the backend) — Ask, Digest, Jobs, Search & Inbox
- [x] Deployed to Fly.io (Docker multi-stage build, persistent volume, auto-migrating schema)

## Quick start (after setup)

```bash
mailchef configure          # one-time: backend URL + API token
mailchef sync                # pull mail from Gmail
mailchef classify && mailchef index   # categorize + embed it
mailchef ask "Any interview schedules this week?"
mailchef digest --now       # generate today's digest on demand
mailchef jobs extract       # scan mail for interviews/replies/rejections; mailchef jobs to view
mailchef chat                # interactive REPL: plain text = ask, /digest /search /jobs /archive ... = actions
```

Or open the web UI at your backend's URL (e.g. `http://localhost:8080`) and paste the same API token when prompted
— four tabs: **Ask**, **Digest**, **Jobs**, **Search & Inbox**.

## Security notes

- Gmail tokens are encrypted at rest (Fernet) and never hardcoded — see
  `backend/.env.example`.
- The agent never treats content inside email bodies as instructions, only
  as data to answer questions about. Only your direct commands (CLI, web UI,
  or chat) are treated as instructions.
- Destructive or irreversible actions (archive, trash, bulk operations)
  always show the affected emails and require explicit confirmation first —
  enforced server-side, not just in the client UI.
- LLM-generated content (digest, chat answers) is derived from email bodies,
  which are attacker-controlled text. The web UI sanitizes rendered markdown
  (DOMPurify) before it ever reaches the DOM, so a crafted email can't inject
  a script tag that survives into a summary.
