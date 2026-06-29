# Google Calendar OAuth Integration
**Tool used:** Claude 3.5 Sonnet
**Date:** June 26, 2026

---

## Context

Wanted to let users connect their Google Calendar so that every booking automatically creates a calendar event for both the patient and the doctor. The integration needed to be opt-in — users who don't connect their Google account should still be able to book normally, the calendar step just silently skips.

The main challenge was token persistence. The OAuth flow happens once in the browser, but the calendar event creation happens later inside a background Celery task. I needed to store the credentials in the database and reconstruct a usable `Credentials` object from them inside the worker.

---

## Prompt I used

> I need Google Calendar OAuth2 in Django. I don't want to force re-authentication every booking. Plan is to store the full credentials JSON in a `GoogleCalendarToken` model. How do I reconstruct a usable `google.oauth2.credentials.Credentials` object from that stored JSON inside a background worker?

## What I got back

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

creds = Credentials.from_authorized_user_info(token.credentials)
service = build('calendar', 'v3', credentials=creds)
```

The stored JSON needs: `token`, `refresh_token`, `token_uri`, `client_id`, `client_secret`, `scopes`. This is exactly what the OAuth flow returns, so storing all of it from the start means no reconstruction issues later.

Used this directly in `services.py` inside `_push_calendar_event()`. Also added token refresh logic — if the access token has expired but a refresh token exists, it refreshes and writes the new token back to the DB so the next task doesn't have to re-authenticate either.

---

## Follow-up: Setup script

Needed a one-time script to walk a user through the browser OAuth consent screen and save the resulting credentials. Should work from the command line during dev setup.

## Prompt I used

> Write a standalone Python script I can run from the project root. Use `InstalledAppFlow` to walk a user through browser-based OAuth and save the resulting credentials to the `GoogleCalendarToken` model. Prompt for a user ID.

## What I got back

```python
import os, sys, django
from google_auth_oauthlib.flow import InstalledAppFlow

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hospital_management.settings")
django.setup()

from core.models import User, GoogleCalendarToken

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

def main():
    user_id = input("Enter user ID to authorize: ")
    user = User.objects.get(pk=int(user_id))

    flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", scopes=SCOPES)
    credentials = flow.run_local_server(port=8090, prompt="consent")

    creds_data = {
        "token":         credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri":     credentials.token_uri,
        "client_id":     credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes":        list(credentials.scopes),
    }

    GoogleCalendarToken.objects.update_or_create(
        user=user,
        defaults={"credentials": creds_data},
    )
    print(f"Token saved for {user.username}")

if __name__ == "__main__":
    main()
```

## What I changed after

- Added a `try/except` around `User.objects.get()` with a clear error message when an invalid ID is entered.
- Added a check for missing `client_secret.json` with instructions pointing to the Google Cloud Console.
- Added a confirmation print showing the user's email alongside username so it's obvious which account was authorized.
- The in-app OAuth flow (via `/calendar/connect/` and `/calendar/callback/` views) was built separately on top of this — the script is only for initial dev setup; production users go through the web-based flow.
