# Hospital Management System (HMS)

A Django-based hospital management application for doctor availability and patient appointment booking, with a separate serverless email notification service and Google Calendar integration.

---

## Setup and Run

### Prerequisites

- **Python 3.10+** (tested on 3.14)
- **Node.js 18+** (for the email service)
- **PostgreSQL** installed and running locally (or use the SQLite fallback — see Database section below)

### 1. Clone and create the virtual environment

```bash
cd hospital-management
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the database

**Option A — PostgreSQL (recommended for production-like testing):**

Create a `.env` file in the project root (parent of `hospital_management/`):

```env
SECRET_KEY=your-secret-key-here
DB_ENGINE=django.db.backends.postgresql
DB_NAME=hms_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

Then create the database:

```bash
psql -U postgres -c "CREATE DATABASE hms_db;"
```

**Option B — SQLite (zero-config, works out of the box):**

Skip the `.env` file entirely. The app defaults to SQLite with a local `db.sqlite3` file. No database server needed.

### 4. Run migrations

```bash
python manage.py migrate
```

### 5. Start the Django server

```bash
python manage.py runserver
```

The app is now live at **http://127.0.0.1:8000/**. Visit `/signup/doctor/` or `/signup/patient/` to create accounts.

### 6. Start the email service (separate terminal)

```bash
cd email-service
npm install            # first time only
python local_server.py
```

This starts the serverless email service at `http://localhost:3000/dev`, which is the default `EMAIL_SERVICE_BASE_URL` the Django app calls. You will see email intent logs in this terminal whenever signup or booking events fire.

To actually send real emails, set `SMTP_USER` and `SMTP_PASS` environment variables with Gmail App Password credentials before starting the server.

### 7. (Optional) Google Calendar setup

```bash
# From the project root
python scripts/setup_google_calendar.py
```

This requires a Google Cloud project with the Calendar API enabled and an OAuth 2.0 Desktop Client credentials JSON file. The script walks you through the OAuth flow and stores tokens in the database. Run it once per user (doctor and patient) to enable calendar event creation on booking.

### 8. (Optional) Celery for async tasks

The app works fully without Celery — email and calendar tasks fall back to synchronous calls or log warnings when no broker is available. To enable background processing:

```bash
# Requires Redis running on localhost:6379
celery -A hospital_management worker --loglevel=info
```

---

## System Architecture

### How the Django app and the serverless email service connect

The system is split into two independent processes that communicate over HTTP:

```
┌─────────────────────────────────┐        HTTP POST         ┌─────────────────────────────┐
│         Django App              │ ───────────────────────►  │   Email Service             │
│    (port 8000)                  │                           │   (port 3000)               │
│                                 │  /email/signup-welcome    │                             │
│  views.py                       │  /email/booking-confirm.  │  handler.py                 │
│    └─► services.py              │                           │    ├─ signup_welcome()       │
│         └─► requests.post()     │                           │    └─ booking_confirmation() │
│              to EMAIL_SERVICE   │                           │         └─► SMTP (Gmail)     │
└─────────────────────────────────┘                           └─────────────────────────────┘
```

Django's `services.py` contains Celery tasks that POST JSON payloads to the email service's HTTP endpoints. The email service is a standalone Python application with a `serverless.yml` defining two Lambda functions (`signupWelcome`, `bookingConfirmation`) and a `local_server.py` wrapper for local testing. The two processes share no database, no models, no imports — the only contract is the HTTP API.

This separation means the email service can be deployed to AWS Lambda independently, scaled to zero when idle, and replaced entirely without touching the Django codebase.

### Data model decisions

Four models, all in `hospital_management.core`:

```
User (extends AbstractUser)
 ├── role: CharField ("DOCTOR" | "PATIENT")
 ├── is_doctor() / is_patient()
 │
 ├──< AvailabilitySlot (FK: doctor → User)
 │     ├── date, start_time, end_time
 │     ├── is_booked: BooleanField
 │     ├── clean(): overlap detection + time validation
 │     └── save(): calls full_clean() to enforce invariants
 │
 ├──< Appointment (FK: patient → User, OneToOne: slot → AvailabilitySlot)
 │     └── created_at
 │
 └──< GoogleCalendarToken (OneToOne: user → User)
       └── credentials: JSONField (OAuth2 token data)
```

**Key decisions:**

- **Single `User` model with a `role` field** rather than separate Doctor/Patient models. Both share username, email, and password — the only difference is access control. A role field on `AbstractUser` avoids multi-table joins on every auth check.
- **`AvailabilitySlot.is_booked` as a boolean flag** rather than deriving booked status from the existence of an `Appointment` record. A dedicated flag enables `select_for_update()` locking on the slot row itself, making the race condition fix straightforward.
- **`Appointment` links patient to slot via `OneToOneField`** — each slot can have exactly one appointment. This is enforced at the database level, not just application logic.
- **`GoogleCalendarToken` stores the full OAuth2 credentials as JSON** — token, refresh_token, client_id, client_secret, scopes. This allows the background task to independently refresh expired tokens without user interaction.

### How role-based access is enforced

Access control operates at three layers:

1. **Decorator layer** (`decorators.py`): `@doctor_required` and `@patient_required` wrap Django's `user_passes_test`. They check `user.is_active` AND the role method. A patient hitting a doctor-only URL gets redirected to login — not a 403, because from the system's perspective they don't have the right identity for that resource.

2. **QuerySet layer** (views): Every slot query filters by `doctor=request.user`. A doctor can never see, modify, or delete another doctor's slots even by crafting URLs with arbitrary PKs, because `get_object_or_404(AvailabilitySlot, pk=pk, doctor=request.user)` will 404.

3. **Model layer** (`limit_choices_to`): `AvailabilitySlot.doctor` has `limit_choices_to={"role": "DOCTOR"}`, and `Appointment.patient` has `limit_choices_to={"role": "PATIENT"}`. This constrains admin forms and provides a documentation-level assertion about data integrity.

### How the Google Calendar integration is structured

The calendar integration is a Celery task (`create_calendar_event_task`) that runs after a successful booking:

1. The `book_slot` view completes the atomic booking transaction first — calendar creation is a separate, best-effort step.
2. The task loads both the patient and doctor `User` objects, then iterates over both.
3. For each user, it checks for a `GoogleCalendarToken`. If none exists (user hasn't completed OAuth), it silently skips — no error, no blocking.
4. If a token exists, it builds `google.oauth2.credentials.Credentials` from the stored JSON, constructs a Calendar API service, and inserts an event with role-appropriate titles ("Appointment with Dr. Smith" for the patient, "Appointment with Jane" for the doctor).
5. The task is wrapped in try/except per-user, so one user's credential failure doesn't prevent the other user's event from being created.

Token setup is handled by `scripts/setup_google_calendar.py`, which runs `InstalledAppFlow` (browser-based OAuth consent) and stores the resulting credentials in the database.

---

## The Design Decision

**The call:** Should booking emails and calendar events fire synchronously inside the `book_slot` view, or asynchronously via Celery tasks?

**Option A — Synchronous.** Call the email service and Google Calendar API directly in the view, inside the same request-response cycle. Simpler stack: no Redis, no Celery, no background workers. The user sees a confirmation only after everything succeeds. Easier to reason about failures — if the email service is down, the user sees an error immediately.

**Option B — Asynchronous via Celery.** Dispatch `.delay()` tasks after the database transaction commits. The booking succeeds immediately; emails and calendar events happen in the background. Requires Redis and a Celery worker.

**My choice: Asynchronous, but with synchronous fallback.**

The booking transaction is the critical path — it involves a `select_for_update()` lock to prevent double-booking. Holding that row lock open while waiting on a 5-second HTTP timeout to an email service, plus two Google Calendar API round-trips, is unacceptable. Under load, this would serialize all bookings behind external API latency and create lock contention that directly causes booking failures.

The booking database write and the notification side-effects have fundamentally different failure modes. A booking must be atomic and fast. An email can be retried in 30 seconds. Coupling them means a Gmail SMTP timeout can cause a patient to lose their slot to a race condition. That's a real bug, not a theoretical concern.

The fallback matters too: when there's no Redis (local dev, early staging), the view catches the broker connection error and logs a warning. The booking still works. The system degrades gracefully instead of crashing on infrastructure that isn't the core product.

---


