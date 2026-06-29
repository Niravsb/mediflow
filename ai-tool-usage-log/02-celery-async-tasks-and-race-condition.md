# Concurrency Control & Async Task Dispatch
**Tool used:** ChatGPT (GPT-4o)
**Date:** June 26, 2026

---

## Context

The booking flow is the riskiest part of the system. Two patients could click "Book" on the same slot at the same millisecond — without proper locking, both requests would read `is_booked=False`, both would pass the check, and both would create an appointment. That's a silent data corruption bug, not a crash.

The fix is `select_for_update()` inside `transaction.atomic()` — lock the slot row, check the flag, write, release. Only one request gets through at a time.

Separately, after booking succeeds I want to fire email and calendar notifications via Celery — but these are side effects, not part of the critical path. The user should get a success response the moment the DB write commits, not after waiting on Gmail SMTP.

---

## Prompt I used

> Building the booking view. I need `transaction.atomic()` + `select_for_update()` to prevent double-bookings, and Celery `.delay()` to fire email and calendar notifications async after the transaction commits. Draft the view logic.

## What I got back

```python
@patient_required
def book_slot(request, pk):
    if request.method != "POST":
        return redirect("patient_dashboard")

    try:
        with transaction.atomic():
            slot = AvailabilitySlot.objects.select_for_update().get(pk=pk)

            if slot.is_booked:
                messages.error(request, "Sorry, this slot was just booked by someone else.")
                return redirect("patient_dashboard")

            slot.is_booked = True
            slot.save()
            Appointment.objects.create(patient=request.user, slot=slot)

            messages.success(request, f"Successfully booked with Dr. {slot.doctor.last_name}!")

    except AvailabilitySlot.DoesNotExist:
        messages.error(request, "Slot not found.")
        return redirect("patient_dashboard")

    send_booking_emails.delay(request.user.email, slot.doctor.email)
    sync_google_calendar.delay(request.user.id, slot.doctor.id)

    return redirect("patient_dashboard")
```

The transaction block was correct. The async dispatch had a problem I spotted immediately.

---

## Problem I identified

If the Celery broker (Redis) is down — which is common in local dev or early staging — calling `.delay()` raises a connection exception. That exception would crash the view *after* the booking already succeeded in the database. The user would see a 500 error for a booking that actually went through.

The booking DB write is the critical path. Celery tasks are best-effort side effects. They should never be able to surface an error to the user.

## Follow-up prompt

> If the Celery broker is down, `.delay()` will raise and crash the view after the DB commit already succeeded. The booking went through but the user sees a 500. Wrap the task dispatches in try/except — log a warning but still return the success redirect.

## Corrected version I asked for

```python
    # Fire async tasks (best-effort — broker being down must not affect the booking response)
    try:
        trigger_booking_email_task.delay(
            patient_email=request.user.email,
            doctor_email=slot.doctor.email,
            date_str=str(slot.date),
            time_str=str(slot.start_time),
        )
    except Exception as exc:
        logger.warning("Email task dispatch failed (broker down?): %s", exc)
```

## What I changed after

- Renamed the task functions to match the actual `services.py` structure (`trigger_booking_email_task`, `trigger_signup_welcome_email_task`).
- Added the Google Calendar sync as a synchronous inline call (`sync_calendar_event_now`) alongside the async Celery task — this means calendar events still get created in local dev even without a Celery worker running.
- Added the `notes` field from `request.POST` to the `Appointment.objects.create()` call.
