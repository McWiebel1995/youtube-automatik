#!/usr/bin/env python3
"""
Einmalig pro Kanal auf deinem eigenen Rechner ausführen, um ein Refresh-Token zu bekommen.

    pip install google-auth-oauthlib
    python scripts/get_token.py client_secret.json

Im Browser mit dem Google-Konto anmelden und den richtigen KANAL auswählen.
Das ausgegebene Refresh-Token als GitHub-Secret speichern (z. B. YT_REFRESH_TOKEN_REGEN).
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube"]

if len(sys.argv) != 2:
    raise SystemExit(__doc__)

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
print("\nRefresh-Token (als GitHub-Secret speichern):\n")
print(creds.refresh_token)
