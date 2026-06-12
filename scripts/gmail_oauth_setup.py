"""One-time Gmail OAuth2 consent helper for GmailApiNotifier.

IMPORTANT — READ FIRST
----------------------
If ``gmail_credentials/token.json`` already exists with a ``refresh_token``
field, you do NOT need to run this script.  The GmailApiNotifier will refresh
the access token automatically.  Only run this script when:

  - You are setting up a brand-new Google Cloud project.
  - The existing token has been revoked or is missing a refresh_token.
  - You want to re-authorise with a different Google account.

GCP setup (one-time, in the browser)
--------------------------------------
1. Go to https://console.cloud.google.com/apis/library
2. Search for "Gmail API" and enable it.
3. Go to https://console.cloud.google.com/apis/credentials
4. Create an OAuth 2.0 Client ID → Application type = "Desktop app".
5. Download the JSON (top right ↓ button) and save it to:
       gmail_credentials/gmailcredentials.json
6. Go to https://console.cloud.google.com/apis/credentials/consent
   Add yourself as a test user (required while the app is "Testing").
7. Run this script (see below).

Running the consent flow
------------------------
From the REPO ROOT (C:\\AIDevelopmentCourse\\Shomer.AI):

    .\\server\\.venv\\Scripts\\python.exe scripts\\gmail_oauth_setup.py

A browser window opens asking you to authorise Shomer.AI to send email.
After consent, the token is written to ``gmail_credentials/token.json``.
The token includes a ``refresh_token`` — the server uses it indefinitely.

Smoke-test (optional — sends ONE real email to verify live sending)
-------------------------------------------------------------------
    .\\server\\.venv\\Scripts\\python.exe scripts\\gmail_oauth_setup.py --smoke your@email.com

This sends a test email from the authorised Gmail account to ``your@email.com``.
It does NOT affect the test suite — no test sends real email.

Environment variables (optional overrides)
------------------------------------------
  GMAIL_CLIENT_JSON  — path to client secrets JSON (default: gmail_credentials/gmailcredentials.json)
  GMAIL_TOKEN_JSON   — path where token is written   (default: gmail_credentials/token.json)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults — must match GmailApiNotifier defaults.
# ---------------------------------------------------------------------------

_DEFAULT_CLIENT_JSON = "gmail_credentials/gmailcredentials.json"
_DEFAULT_TOKEN_JSON = "gmail_credentials/token.json"
_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _check_google_deps() -> None:
    """Verify google-auth packages are installed; print install instructions if not."""
    try:
        import google.auth  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        import googleapiclient  # noqa: F401
    except ImportError:
        print(
            "ERROR: google-auth packages are not installed.\n"
            "Install them with:\n"
            "    server\\.venv\\Scripts\\python.exe -m pip install "
            "google-auth google-auth-oauthlib google-api-python-client",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_consent(client_json: str, token_json: str) -> None:
    """Run the InstalledAppFlow browser consent and write token.json."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not Path(client_json).exists():
        print(
            f"ERROR: client-secrets file not found at '{client_json}'.\n"
            "Download it from Google Cloud Console → Credentials → OAuth 2.0 Client IDs.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading client secrets from: {client_json}")
    flow = InstalledAppFlow.from_client_secrets_file(client_json, scopes=_SCOPES)
    print("Opening browser for consent…  (if it doesn't open, copy the URL manually)")
    creds = flow.run_local_server(port=0, open_browser=True)

    # Write token (includes refresh_token — do NOT lose this file).
    Path(token_json).parent.mkdir(parents=True, exist_ok=True)
    with open(token_json, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print(f"\nToken written to: {token_json}")
    print("The GmailApiNotifier will use this token at runtime.")


def _verify_token(token_json: str) -> None:
    """Load the stored token and verify it can be refreshed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not Path(token_json).exists():
        print(f"ERROR: token file not found at '{token_json}'.", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(token_json, scopes=_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            print("Access token expired — refreshing…")
            creds.refresh(Request())
            with open(token_json, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())
            print("Token refreshed and saved.")
        else:
            print(
                "ERROR: Token is invalid and cannot be refreshed. "
                "Run this script without --verify to re-authorise.",
                file=sys.stderr,
            )
            sys.exit(1)
    print(f"Token is valid. Expiry: {creds.expiry}")


def _smoke_test(token_json: str, to_address: str) -> None:
    """Send a single test email to verify live sending works."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    print(f"Sending smoke-test email to: {to_address}")

    creds = Credentials.from_authorized_user_file(token_json, scopes=_SCOPES)
    if not creds.valid:
        creds.refresh(Request())

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    # Resolve sender via profile.
    profile = service.users().getProfile(userId="me").execute()
    from_address = profile.get("emailAddress", "me")

    body = (
        "This is an automated smoke-test from scripts/gmail_oauth_setup.py.\n"
        "If you received this, the GmailApiNotifier credential chain works correctly.\n\n"
        "Shomer.AI"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_address
    msg["From"] = from_address
    msg["Subject"] = "Shomer.AI — Gmail smoke test"

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Sent. Gmail message ID: {result.get('id', '?')}")
    print("Check your inbox — the smoke-test email should arrive within seconds.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time Gmail OAuth2 consent for GmailApiNotifier",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--client-json",
        default=os.environ.get("GMAIL_CLIENT_JSON", _DEFAULT_CLIENT_JSON),
        help=f"Path to OAuth client-secrets JSON (default: {_DEFAULT_CLIENT_JSON})",
    )
    parser.add_argument(
        "--token-json",
        default=os.environ.get("GMAIL_TOKEN_JSON", _DEFAULT_TOKEN_JSON),
        help=f"Path where the token will be written (default: {_DEFAULT_TOKEN_JSON})",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify (and refresh if needed) an existing token without re-authorising",
    )
    parser.add_argument(
        "--smoke",
        metavar="TO_EMAIL",
        help="Send a live smoke-test email to TO_EMAIL after authorising",
    )
    args = parser.parse_args()

    _check_google_deps()

    if args.verify:
        _verify_token(args.token_json)
        if args.smoke:
            _smoke_test(args.token_json, args.smoke)
        return

    # Check if an existing token already has a refresh_token — skip consent if so.
    if Path(args.token_json).exists():
        try:
            with open(args.token_json, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("refresh_token"):
                print(
                    f"Existing token at '{args.token_json}' already has a refresh_token.\n"
                    "No new consent is needed.  Use --verify to check validity.\n"
                    "Use --smoke <email> to send a test email."
                )
                if args.smoke:
                    _smoke_test(args.token_json, args.smoke)
                return
        except Exception:  # noqa: BLE001 — malformed JSON → run consent
            pass

    _run_consent(args.client_json, args.token_json)
    if args.smoke:
        _smoke_test(args.token_json, args.smoke)


if __name__ == "__main__":
    main()
