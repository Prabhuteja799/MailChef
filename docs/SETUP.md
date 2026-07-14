# MailChef setup

Full setup, stage by stage: Google OAuth, running the backend locally,
verifying each capability with curl, deploying to Fly.io, then installing
the [CLI](#12-install-the-cli) and [web UI](#13-web-ui) you'll actually use
day to day.

## 1. Google Cloud: OAuth client + Gmail API

1. Go to https://console.cloud.google.com/ and create a project (or reuse one).
2. **APIs & Services > Library** → enable the **Gmail API**.
3. **APIs & Services > OAuth consent screen**:
   - User type: External (fine for personal use — you'll add yourself as a
     test user, no Google verification review needed while in "Testing" mode).
   - Add your Gmail address under **Test users**.
   - Scopes: you don't need to add `gmail.modify` here; MailChef requests it
     directly in the OAuth flow.
4. **APIs & Services > Credentials > Create Credentials > OAuth client ID**:
   - Application type: **Web application**.
   - Authorized redirect URIs: add both, so it works locally and once deployed:
     - `http://localhost:8080/auth/gmail/callback`
     - `https://<your-app>.fly.dev/auth/gmail/callback`
   - Save the generated **Client ID** and **Client Secret**.

## 2. Generate secrets

```bash
# Fernet key for encrypting Gmail tokens at rest
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Bearer token the CLI uses to call the backend
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put both into `backend/.env` (copy from `.env.example` first) along with your
Google client ID/secret and your `OPENAI_API_KEY`.

## 3. Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # then fill in the values from steps 1-2
uvicorn app.main:app --reload --port 8080
```

## 4. Connect your Gmail account (one-time)

```bash
curl -s http://localhost:8080/auth/gmail/start | python3 -m json.tool
```

Open the returned `authorization_url` in a browser, sign in, approve
`gmail.modify` access. You'll land on a "MailChef connected to Gmail" page —
that means an encrypted refresh token is now stored in `backend/data/mailchef.db`.

## 5. Run a sync and sanity-check it

```bash
curl -s -X POST http://localhost:8080/sync/run \
  -H "Authorization: Bearer <MAILCHEF_API_TOKEN from .env>" | python3 -m json.tool

curl -s "http://localhost:8080/messages?limit=5" \
  -H "Authorization: Bearer <MAILCHEF_API_TOKEN from .env>" | python3 -m json.tool
```

You should see your most recent messages (subject, sender, date, unread
status).

## 6. Classify and index your mail (stage b)

```bash
TOKEN="<MAILCHEF_API_TOKEN from .env>"

curl -s -X POST http://localhost:8080/classify/run -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -s -X POST http://localhost:8080/index/run    -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# see/edit the configured categories: backend/app/classification/categories.json
# (or drop an override at backend/data/categories.json)
curl -s http://localhost:8080/categories -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# try hybrid (semantic + keyword) retrieval directly, no LLM synthesis yet
curl -s "http://localhost:8080/search?q=interview+this+week&limit=10" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

`classify/run` uses the cheap-tier model (`CLASSIFIER_MODEL`) to bucket
unclassified mail into your configured categories. `index/run` embeds new
mail into Chroma (`EMBEDDING_MODEL`) and keeps a SQLite FTS5 keyword index in
sync. `/search` fuses both via reciprocal rank fusion and supports
`category`, `sender`, `after`, `before`, and `unread_only` filters. Run
`classify/run` then `index/run` after every `sync/run` so category metadata
is fresh in the vector store.

## 7. Ask natural-language questions (stage c)

```bash
curl -s -X POST http://localhost:8080/query \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question": "Any interview schedules this week?"}' | python3 -m json.tool
```

Under the hood: a cheap-tier call turns the question into search terms +
filters (category/sender/date range, resolving "this week" etc. against
`DIGEST_TIMEZONE`), `hybrid_search` retrieves matching emails, and the
strong-tier model (`ANSWER_MODEL`) answers using only those emails — it's
told explicitly to say so rather than guess if nothing relevant is found.
The response includes a `sources` list (id/from/subject/date) so you can
verify what the answer was actually grounded in.

Semantic matches below the similarity threshold (`SEMANTIC_DISTANCE_THRESHOLD`)
are dropped before reaching the LLM, so an unrelated question can't drag in
"closest but irrelevant" emails as false context — worth tightening or
loosening once you see how it behaves on your real inbox.

## 8. Inbox actions (stage d)

Safe, single-message, reversible actions (mark read/unread, star/unstar,
add/remove a label) execute immediately:

```bash
curl -s -X POST http://localhost:8080/actions/execute \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action": "mark_read", "message_ids": ["<gmail-message-id>"]}'
```

Anything destructive (archive, trash) or touching more than one message —
always requires propose, then a separate confirm call:

```bash
# 1. propose — resolves the target (by id or by search) and shows what would be affected, touches nothing yet
curl -s -X POST http://localhost:8080/actions/propose \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action": "archive", "search": "promotional emails", "category": "promotion", "limit": 20}' \
  | python3 -m json.tool
# -> {"proposal_id": "...", "affected_count": 7, "affected": [ ...emails... ]}

# 2. only after reviewing `affected`, confirm using the returned proposal_id
curl -s -X POST http://localhost:8080/actions/confirm \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"proposal_id": "<proposal_id from step 1>"}'

# or cancel instead:
curl -s -X POST http://localhost:8080/actions/cancel \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"proposal_id": "<proposal_id>"}'
```

Proposals expire after `ACTION_CONFIRMATION_TTL_MINUTES` (default 10) and
can only be confirmed once. `execute`/`propose` both accept either explicit
`message_ids` or a `search` (+ optional `category`/`sender`/`after`/`before`/
`unread_only`) that resolves through the same hybrid search as `/query` —
but the search only ever reads email content as data to match against, it
never lets an email's own text decide what action gets taken. `GET /labels`
lists your Gmail labels (id + name) for `add_label`/`remove_label`.

## 9. Morning digest (stage e)

Runs automatically every day at `DIGEST_HOUR:DIGEST_MINUTE` in
`DIGEST_TIMEZONE` (an in-process APScheduler job — this is why `fly.toml`
keeps a machine always running rather than scaling to zero). Also available
on demand:

```bash
# "give me my summary now" — re-syncs, classifies, re-indexes, then
# generates a fresh digest (same pipeline the scheduled job runs)
curl -s -X POST http://localhost:8080/digest/run \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# fetch the most recently generated digest without recomputing
curl -s http://localhost:8080/digest/latest -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

The digest groups unread mail by your configured categories, and separately
extracts action items ("needs a reply") and interview/meeting schedule
entries with dates — each referencing the source email id. If there's no
unread mail, it skips the LLM call entirely rather than paying for an empty
summary.

## 10. Job application tracker

Extracts interview invites, replies, and rejections from your job-search
mail (`interview`/`recruiter`/`update` categories only) and matches each one
to a per-company application with a status derived from the most recent
event.

```bash
# scans mail scoped to the last N days; omit since_days to scan everything pending
curl -s -X POST "http://localhost:8080/jobs/extract?since_days=14" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

curl -s http://localhost:8080/jobs -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -s http://localhost:8080/jobs/<application-id> -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Company matching is best-effort (the extraction prompt asks for the parent
brand name specifically, e.g. "Citi" not "Citi Scaled Technical Hiring NAM")
— not exact entity resolution, so the same company can occasionally split
across two entries under different extracted names. Interview/moving-forward/
offer events are itemized individually wherever they're surfaced (digest,
CLI, web); rejections are only counted, since an active search can produce
dozens per week and itemizing them would bury the signal that actually
matters. This is wired into the scheduled digest pipeline too (`/digest/run`
scopes it the same way as classify/index, via `since_days`/`INITIAL_SYNC_DAYS`).

## 11. Deploy to Fly.io

```bash
brew install flyctl   # or see https://fly.io/docs/hands-on/install-flyctl/
flyctl auth login     # opens a browser

cd ..   # run from the repo root — the build needs both backend/ and web/
flyctl apps create mailchef-backend   # pick your own globally-unique name if this is taken
flyctl volumes create mailchef_data --region iad --size 1 -a mailchef-backend --yes

# Push every value from your local backend/.env as a Fly secret (never commit .env):
flyctl secrets set -a mailchef-backend \
  GOOGLE_CLIENT_ID=... \
  GOOGLE_CLIENT_SECRET=... \
  GOOGLE_OAUTH_REDIRECT_URI=https://<your-app>.fly.dev/auth/gmail/callback \
  TOKEN_ENCRYPTION_KEY=... \
  MAILCHEF_API_TOKEN=... \
  OPENAI_API_KEY=...

flyctl deploy -a mailchef-backend --config backend/fly.toml --dockerfile backend/Dockerfile
```

**Run this from the repo root, not from `backend/`.** `fly.toml`'s
`[build] context = ".."` is meant to make the build context the repo root
(so the Dockerfile's frontend stage can reach `web/`), but in practice
`flyctl deploy`'s context resolution follows your current directory, not the
`context` field, when invoked as a plain `fly deploy` from inside `backend/`
— it'll silently build with `backend/` as context instead, and fail with
`COPY web/ ./: "/web": not found` (or copy your local `backend/.venv` and
`backend/data/`, including your real synced mailbox database, into the
build upload). Always pass `--config backend/fly.toml --dockerfile
backend/Dockerfile` explicitly from the repo root, which is also why
`.dockerignore` exists at the repo root — it excludes `backend/.venv`,
`backend/data/`, `cli/`, and `docs/` from the build context regardless.

Before connecting Gmail on the deployed instance, add
`https://<your-app>.fly.dev/auth/gmail/callback` to your OAuth client's
Authorized redirect URIs in Google Cloud Console (keep the localhost one
too). Then repeat step 4 against `https://<your-app>.fly.dev` instead of
`localhost:8080` — **this is a separate, empty database from your local
one**; Gmail needs to be connected there independently.

If `https://<your-app>.fly.dev` doesn't resolve right after deploying, that's
normal DNS propagation (a minute or two, occasionally longer depending on
your resolver) — the app itself is up as soon as `flyctl deploy` finishes;
`flyctl status -a <your-app>` shows `started` once the machine is healthy.

Notes on this deployment shape:
- `fly.toml` sets `min_machines_running = 1` so the process (and its
  in-process digest scheduler) keeps running even with no incoming requests —
  this costs a small always-on fee instead of Fly's scale-to-zero free tier.
- The Fly volume persists `/data`: the SQLite DB (messages, sync state,
  encrypted OAuth token, digest history, tracked job applications) and the
  Chroma vector store.
- Schema changes (new model fields) auto-migrate additively on startup
  (`backend/app/db/database.py`) — safe to redeploy after pulling model
  changes without manually altering the Fly volume's database.

## 12. Install the CLI

This is what you actually run day to day, once the backend (local or
deployed) is up.

```bash
cd cli
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

mailchef configure   # prompts for backend URL + MAILCHEF_API_TOKEN, saves to ~/.mailchef/config.json (chmod 600)
```

Then:

```bash
mailchef sync                        # pull new mail from Gmail
mailchef classify && mailchef index  # categorize + embed it
mailchef ask "Any interview schedules this week?"
mailchef search "landlord" --unread
mailchef digest                      # latest digest
mailchef digest --now                # regenerate now ("give me my summary now")
mailchef jobs extract                # scan mail for interview/reply/rejection events
mailchef jobs                        # list tracked applications
mailchef jobs show <application-id>  # full email timeline for one application
mailchef mark-read <message-id>      # safe single action, runs immediately
mailchef archive --search "promotional emails" --category promotion
  # -> shows every matching email and asks y/n before touching Gmail
mailchef chat                        # interactive: plain text asks a question,
                                      # /digest /search /jobs /archive /trash /mark-read /star /sync run actions
```

`mailchef --help` lists every command; each subcommand supports `--help` too.
Every archive/trash/bulk action prints the full affected-email list and
requires an explicit "y" — nothing destructive ever runs silently.

## 13. Web UI

The web UI is a React SPA served directly by the backend — no separate
server, no CORS setup, one URL.

**Local development** (hot reload, talks to a backend running on `:8080`):

```bash
cd web
npm install
npm run dev   # opens on :5173; paste http://localhost:8080 as the backend URL when it asks
```

**Production build**, served by the backend itself:

```bash
cd web
npm install
npm run build   # outputs web/dist

# restart the backend — app/main.py auto-mounts web/dist at / if it exists
cd ../backend && uvicorn app.main:app --port 8080
```

Then open `http://localhost:8080` and paste your `MAILCHEF_API_TOKEN` — same
token the CLI uses, stored in the browser's localStorage, sent as a bearer
header on every request. Four tabs:
- **Ask** — natural-language Q&A, with persistent chat history (localStorage)
- **Digest** — latest/generate now, rendered as real components (stat tiles,
  color-coded job highlights) rather than a markdown blob
- **Jobs** — the job tracker: a "needs your attention" section for
  interview/moving-forward/offer, and a filterable/searchable table for
  everything else
- **Search & Inbox** — hybrid search, or leave the query empty to just
  browse recent mail like Gmail; archive/trash/bulk actions always show the
  affected emails and require an explicit confirm click before touching
  Gmail, same guarantee as the CLI

`backend/Dockerfile` builds the frontend in a separate stage and copies the
static output into the image, so a Fly.io deploy (per step 11) ships the web
UI automatically — verified with a real `docker build` + `docker run` of the
multi-stage image, and with a real deploy to Fly.io.
