import os

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlmodel import Session, select

from app.config import settings
from app.db.models import OAuthToken

# If this OAuth client already has broader Gmail scopes granted on the
# account (e.g. from another app using the same client), Google returns
# those alongside what we asked for, and oauthlib raises a Warning by
# default when the granted scopes differ from the requested ones. That's
# expected/benign here — relax it rather than treating it as fatal.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# gmail.modify covers read, mark read/unread, star, label, archive, and trash
# (move to Trash) but NOT permanent delete — matches the "read + modify" ask
# while keeping permanent deletion out of the agent's reach entirely.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_oauth_redirect_uri],
        }
    }


def _fernet() -> Fernet:
    return Fernet(settings.token_encryption_key.encode())


# PKCE (code_verifier/code_challenge) is for public clients that can't hold
# a secret. This is a confidential "Web application" OAuth client (it has a
# client_secret), so PKCE isn't needed — the client_secret already proves
# who's asking. google-auth-oauthlib auto-adds PKCE by default, which Google
# doesn't accept cleanly for this client type; disable it explicitly.


def get_authorization_url() -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, autogenerate_code_verifier=False)
    flow.redirect_uri = settings.google_oauth_redirect_uri
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forces a refresh_token even on re-auth
    )
    return auth_url


def exchange_code_for_credentials(code: str) -> Credentials:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, autogenerate_code_verifier=False)
    flow.redirect_uri = settings.google_oauth_redirect_uri
    flow.fetch_token(code=code)
    return flow.credentials


def save_credentials(session: Session, credentials: Credentials) -> None:
    if not credentials.refresh_token:
        raise ValueError(
            "Google did not return a refresh_token. Revoke MailChef's access at "
            "https://myaccount.google.com/permissions and re-run /auth/gmail/start "
            "so Google issues a fresh one."
        )

    fernet = _fernet()
    existing = session.exec(select(OAuthToken).where(OAuthToken.provider == "gmail")).first()
    row = existing or OAuthToken(provider="gmail", refresh_token_encrypted="")

    row.refresh_token_encrypted = fernet.encrypt(credentials.refresh_token.encode()).decode()
    row.access_token_encrypted = (
        fernet.encrypt(credentials.token.encode()).decode() if credentials.token else None
    )
    row.token_expiry = credentials.expiry
    row.scopes = ",".join(credentials.scopes or SCOPES)

    session.add(row)
    session.commit()


def load_credentials(session: Session) -> Credentials | None:
    row = session.exec(select(OAuthToken).where(OAuthToken.provider == "gmail")).first()
    if row is None:
        return None

    fernet = _fernet()
    credentials = Credentials(
        token=fernet.decrypt(row.access_token_encrypted.encode()).decode()
        if row.access_token_encrypted
        else None,
        refresh_token=fernet.decrypt(row.refresh_token_encrypted.encode()).decode(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=row.scopes.split(",") if row.scopes else SCOPES,
    )
    credentials.expiry = row.token_expiry

    if not credentials.valid:
        credentials.refresh(Request())
        save_credentials(session, credentials)

    return credentials
