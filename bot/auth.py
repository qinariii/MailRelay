import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from bot.logger import logger

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def authenticate(credentials_path, token_path):
    creds = None

    if os.path.exists(token_path) and os.path.getsize(token_path) > 0:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        logger.info("Token found, loading from %s", token_path)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Token expired, refreshing…")
                creds.refresh(Request())
            except Exception as e:
                logger.warning("Refresh failed (%s), removing old token…", e)
                os.remove(token_path)
                creds = None
        if not creds or not creds.valid:
            if not os.path.exists(credentials_path):
                logger.error(
                    "Credentials file not found: %s", credentials_path
                )
                raise FileNotFoundError(
                    f"Credentials file not found: {credentials_path}. "
                    "Download from Google Cloud Console."
                )
            logger.info("Starting OAuth 2.0 flow…")
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES
            )
            # try local server first, fall back to console
            try:
                creds = flow.run_local_server(port=0)
            except Exception:
                logger.info(
                    "Local server not available (remote/headless). "
                    "Using console mode…"
                )
                flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
                auth_url, _ = flow.authorization_url(prompt="consent")
                print("\n" + "=" * 60)
                print("Open this URL in your browser:")
                print(f"\n  {auth_url}\n")
                print("=" * 60)
                code = input("Enter authorization code: ").strip()
                flow.fetch_token(code=code)
                creds = flow.credentials

        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
        logger.info("Token saved to %s", token_path)

    return creds


def get_gmail_service(credentials_path, token_path):
    creds = authenticate(credentials_path, token_path)
    service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail API service created")
    return service