"""Optional: save an outreach email as a Gmail draft instead of (or as well
as) a local .txt file. This NEVER sends anything - it only ever calls the
Gmail drafts.create API, and the human still has to open Gmail and hit send
themselves.

Requires the `gmail` extra (`pip install 'jobscout[gmail]'`) and your own
Google Cloud OAuth client credentials - see the README for setup. Without
either, callers should catch GmailDraftError and fall back to a local file;
`jobscout daily --gmail-draft` does exactly that.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:  # pragma: no cover - exercised via the [gmail] extra
    build = None

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
DEFAULT_CREDENTIALS_PATH = "credentials.json"
DEFAULT_TOKEN_PATH = "data/.gmail_token.json"


class GmailDraftError(RuntimeError):
    pass


def _load_credentials(credentials_path: str, token_path: str):
    token_file = Path(token_path)
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(credentials_path).exists():
                raise GmailDraftError(
                    f"No Google OAuth credentials at {credentials_path}. Download an "
                    "OAuth client secret from Google Cloud Console (Gmail API, Desktop "
                    "app type) and save it there - see the README's Gmail setup section."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())
    return creds


def create_draft(*, to: str, subject: str, body: str,
                  credentials_path: str = DEFAULT_CREDENTIALS_PATH,
                  token_path: str = DEFAULT_TOKEN_PATH, service=None) -> str:
    """Creates a Gmail draft and returns its id. Pass `service` (an
    already-built Gmail API resource) to skip OAuth entirely - mainly so
    tests can inject a fake one without the google client libs installed.
    """
    if service is None:
        if build is None:
            raise GmailDraftError(
                "Gmail integration needs the 'gmail' extra: "
                "pip install 'jobscout[gmail]'"
            )
        creds = _load_credentials(credentials_path, token_path)
        service = build("gmail", "v1", credentials=creds)

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        draft = service.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
    except Exception as exc:  # the google client's own broad error hierarchy
        raise GmailDraftError(f"Gmail API call failed: {exc}") from exc

    draft_id = draft.get("id")
    if not draft_id:
        raise GmailDraftError("Gmail API returned no draft id")
    return draft_id
