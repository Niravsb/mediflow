import logging
import requests
from django.conf import settings
from celery import shared_task
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from .models import GoogleCalendarToken, User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helper — creates a Google Calendar event for one user.
# Used by both the async Celery task AND the synchronous inline path.
# ---------------------------------------------------------------------------

def _push_calendar_event(user, doctor, patient, date_str, start_time_str, end_time_str):
    """Push a single calendar event for `user`. Returns True on success."""
    token = GoogleCalendarToken.objects.filter(user=user).first()
    if not token:
        logger.info("No Google Calendar token for user %s — skipping.", user.username)
        return False

    creds = Credentials.from_authorized_user_info(token.credentials)

    # Auto-refresh expired OAuth2 tokens
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.credentials = {
                "token":         creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri":     creds.token_uri,
                "client_id":     creds.client_id,
                "client_secret": creds.client_secret,
                "scopes":        list(creds.scopes),
            }
            token.save()

    if not creds.valid:
        logger.error("Token for user %s is invalid and could not be refreshed.", user.username)
        return False

    service = build('calendar', 'v3', credentials=creds)

    if user.role == User.ROLE_PATIENT:
        title = f"Appointment with Dr. {doctor.last_name}"
    else:
        title = f"Appointment with {patient.get_full_name() or patient.username}"

    # Build RFC 3339 datetime strings (Google requires timezone-aware)
    tz = settings.TIME_ZONE  # e.g. 'Asia/Kolkata' or 'UTC'
    event = {
        'summary': title,
        'description': 'Booked via Hospital Management System',
        'start': {
            'dateTime': f"{date_str}T{start_time_str}",
            'timeZone': tz,
        },
        'end': {
            'dateTime': f"{date_str}T{end_time_str}",
            'timeZone': tz,
        },
    }
    service.events().insert(calendarId='primary', body=event).execute()
    logger.info("Calendar event created for user %s on %s", user.username, date_str)
    return True


def sync_calendar_event_now(patient_id, doctor_id, date_str, start_time_str, end_time_str):
    """
    Synchronous (inline) calendar sync — called directly from the view.
    Safe to call even if either user has no token (silently skips them).
    Returns a list of usernames for whom the event was created.
    """
    try:
        patient = User.objects.get(pk=patient_id)
        doctor  = User.objects.get(pk=doctor_id)
    except User.DoesNotExist:
        logger.error("sync_calendar_event_now: user not found.")
        return []

    created_for = []
    for user in [patient, doctor]:
        try:
            ok = _push_calendar_event(user, doctor, patient, date_str, start_time_str, end_time_str)
            if ok:
                created_for.append(user.username)
        except Exception as exc:
            logger.error("Inline calendar sync failed for %s: %s", user.username, exc)

    return created_for


@shared_task
def trigger_signup_welcome_email_task(email, first_name):
    """Call the serverless email service to send a welcome email on sign up."""
    try:
        payload = {"email": email, "first_name": first_name}
        requests.post(
            f"{settings.EMAIL_SERVICE_BASE_URL}/email/signup-welcome",
            json=payload,
            timeout=5
        )
    except Exception as e:
        logger.error("Async signup welcome email failed: %s", e)


@shared_task
def trigger_booking_email_task(patient_email, doctor_email, date_str, time_str):
    try:
        payload = {
            "patient_email": patient_email,
            "doctor_email":  doctor_email,
            "date":          date_str,
            "time":          time_str
        }
        requests.post(
            f"{settings.EMAIL_SERVICE_BASE_URL}/email/booking-confirmation",
            json=payload,
            timeout=5
        )
    except Exception as e:
        logger.error("Async booking email failed: %s", e)


@shared_task
def create_calendar_event_task(patient_id, doctor_id, date_str, start_time_str, end_time_str):
    """Async Celery task wrapper — delegates to the shared helper."""
    try:
        patient = User.objects.get(pk=patient_id)
        doctor  = User.objects.get(pk=doctor_id)
    except User.DoesNotExist:
        logger.error("Calendar sync failed: User not found.")
        return

    for user in [patient, doctor]:
        try:
            _push_calendar_event(user, doctor, patient, date_str, start_time_str, end_time_str)
        except Exception as e:
            logger.error("Calendar sync failed for user %s: %s", user.username, e)