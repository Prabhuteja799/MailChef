# MailChef setup

Full setup, stage by stage: Google OAuth, running the backend locally,
verifying each capability with curl, deploying to Fly.io, then installing
the CLI you'll actually use day to day (§10).

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

## 6. Deploy to Fly.io (do this once you're happy with stage (a) locally)

```bash
brew install flyctl   # or see https://fly.io/docs/hands-on/install-flyctl/
fly auth login

cd backend
fly launch --no-deploy   # creates the app, keep the generated name in sync with fly.toml
fly volumes create mailchef_data --size 1   # persistent volume for SQLite + Chroma

# Push every value from your local .env as a Fly secret (never commit .env):
fly secrets set \
  GOOGLE_CLIENT_ID=... \
  GOOGLE_CLIENT_SECRET=... \
  GOOGLE_OAUTH_REDIRECT_URI=https://<your-app>.fly.dev/auth/gmail/callback \
  TOKEN_ENCRYPTION_KEY=... \
  MAILCHEF_API_TOKEN=... \
  OPENAI_API_KEY=...

fly deploy
```

Then repeat step 4 against `https://<your-app>.fly.dev` instead of
`localhost:8080` to connect Gmail on the deployed instance.

Notes on this deployment shape:
- `fly.toml` sets `min_machines_running = 1` so the process (and later, its
  in-process digest scheduler) keeps running even with no incoming requests —
  this costs a small always-on fee instead of Fly's scale-to-zero free tier.
- The Fly volume persists `backend/data/`: the SQLite DB (messages, sync
  state, encrypted OAuth token) and the Chroma vector store (added in stage b).

## 10. Install the CLI

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
mailchef mark-read <message-id>      # safe single action, runs immediately
mailchef archive --search "promotional emails" --category promotion
  # -> shows every matching email and asks y/n before touching Gmail
mailchef chat                        # interactive: plain text asks a question,
                                      # /digest /search /archive /trash /mark-read /star /sync run actions
```

`mailchef --help` lists every command; each subcommand supports `--help` too.
Every archive/trash/bulk action prints the full affected-email list and
requires an explicit "y" — nothing destructive ever runs silently.

## 11. Web UI

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
header on every request. Three views: **Ask** (natural-language Q&A),
**Digest** (latest/generate now), **Search & Inbox** (hybrid search +
actions — archive/trash/bulk always show the affected emails and require
an explicit confirm click before touching Gmail, same guarantee as the CLI).

`backend/Dockerfile` builds the frontend in a separate stage and copies the
static output into the image, so a Fly.io deploy (`fly deploy` from
`backend/`, per step 6) ships the web UI automatically — verified with a
real `docker build` + `docker run` of the multi-stage image.
