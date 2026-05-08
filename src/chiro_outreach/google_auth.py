from pathlib import Path
from typing import Sequence

from .config import load_config


OUTREACH_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_credentials(scopes: Sequence[str]):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as error:
        raise RuntimeError(
            "Google API dependencies are not installed. Run `pip install -r chiro_outreach/requirements.txt` first."
        ) from error

    config = load_config()
    client_secret_path = Path(config["google_oauth_client_secret"])
    token_path = Path(config["google_oauth_token"])
    token_path.parent.mkdir(parents=True, exist_ok=True)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.valid and credentials_have_scopes(creds, scopes):
        return creds

    if creds and creds.expired and creds.refresh_token and credentials_have_scopes(creds, scopes):
        creds.refresh(Request())
    else:
        if not client_secret_path.exists():
            raise RuntimeError(
                f"Google OAuth client secret not found at {client_secret_path}. "
                "Create an OAuth desktop client in Google Cloud and place the downloaded JSON there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes)
        creds = flow.run_local_server(port=0)

    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def credentials_have_scopes(creds, scopes: Sequence[str]) -> bool:
    if hasattr(creds, "has_scopes"):
        return bool(creds.has_scopes(scopes))
    granted = set(getattr(creds, "scopes", []) or [])
    return set(scopes).issubset(granted)


def google_service(api_name: str, version: str, scopes: Sequence[str]):
    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Google API dependencies are not installed. Run `pip install -r chiro_outreach/requirements.txt` first."
        ) from error

    return build(api_name, version, credentials=get_credentials(scopes))
