"""
Google Calendar OAuth2 setup helper for HMS.

This script walks you through the OAuth2 flow to get credentials
and stores them in the GoogleCalendarToken model for a given user.

Prerequisites:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or reuse one)
  3. Enable "Google Calendar API"
  4. Go to "Credentials" → Create "OAuth 2.0 Client ID" (Desktop app type)
  5. Download the JSON file and save it as:
       email-service/client_secret.json
     OR pass the path via --credentials-file

Usage:
    cd <project-root>
    .venv\Scripts\python manage.py shell < scripts\setup_google_calendar.py

    OR run interactively:
    .venv\Scripts\python scripts\setup_google_calendar.py
"""
import os
import sys
import json

# Bootstrap Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hospital_management.settings")

import django
django.setup()

from google_auth_oauthlib.flow import InstalledAppFlow
from hospital_management.core.models import GoogleCalendarToken, User

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

DEFAULT_CREDS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "client_secret.json"
)


def main():
    # --- 1. Locate client_secret.json ---
    creds_path = DEFAULT_CREDS_PATH
    if not os.path.exists(creds_path):
        creds_path = input("Path to your OAuth client_secret.json: ").strip()
        if not os.path.exists(creds_path):
            print(f"ERROR: File not found: {creds_path}")
            sys.exit(1)

    # --- 2. Pick a user ---
    users = User.objects.all()
    if not users.exists():
        print("No users in the database. Sign up first via the web UI.")
        sys.exit(1)

    print("\nAvailable users:")
    for u in users:
        has_token = "✓" if GoogleCalendarToken.objects.filter(user=u).exists() else " "
        print(f"  [{has_token}] {u.id}: {u.username} ({u.role})")

    user_id = input("\nEnter user ID to authorize: ").strip()
    try:
        user = User.objects.get(pk=int(user_id))
    except (User.DoesNotExist, ValueError):
        print("Invalid user ID.")
        sys.exit(1)

    # --- 3. Run OAuth2 flow ---
    print(f"\nStarting OAuth2 flow for {user.username}...")
    print("A browser window will open. Log in and grant Calendar access.\n")

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, scopes=SCOPES)
    credentials = flow.run_local_server(port=8090, prompt="consent")

    # --- 4. Store credentials ---
    creds_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or SCOPES),
    }

    token_obj, created = GoogleCalendarToken.objects.update_or_create(
        user=user,
        defaults={"credentials": creds_data},
    )

    action = "Created" if created else "Updated"
    print(f"\n✓ {action} GoogleCalendarToken for {user.username}")
    print("  Calendar events will now be created on booking.\n")


if __name__ == "__main__":
    main()
