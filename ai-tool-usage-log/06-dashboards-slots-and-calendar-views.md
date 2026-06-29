# Dashboards, Slot Management, Access Control & Calendar Views
**Tool used:** Claude 3.5 Sonnet
**Date:** June 25–26, 2026

---

## Context

With auth in place, needed the four main functional areas: role-based access control via decorators, doctor and patient dashboards, slot CRUD for doctors, and the Google Calendar OAuth views for the in-app connect flow.

---

## Part 1: Role-based access decorators

Django's `@login_required` only checks if a user is authenticated — not what role they have. A patient hitting `/slots/create/` would pass `@login_required` but shouldn't be there. Needed custom decorators that check both authentication and role in one step.

## Prompt I used

> Write `@doctor_required` and `@patient_required` decorators for Django views. They should check that the user is both active and has the correct role. Use `user_passes_test` as the base. Redirect to the login page on failure.

## What I got back

```python
from django.contrib.auth.decorators import user_passes_test

def doctor_required(function=None, redirect_field_name='next', login_url='login'):
    actual_decorator = user_passes_test(
        lambda u: u.is_active and u.is_doctor(),
        login_url=login_url,
        redirect_field_name=redirect_field_name
    )
    if function:
        return actual_decorator(function)
    return actual_decorator

def patient_required(function=None, redirect_field_name='next', login_url='login'):
    actual_decorator = user_passes_test(
        lambda u: u.is_active and u.is_patient(),
        login_url=login_url,
        redirect_field_name=redirect_field_name
    )
    if function:
        return actual_decorator(function)
    return actual_decorator
```

Used exactly as provided. Redirecting to login (not a 403) is intentional — from the system's perspective, the user doesn't have the right identity for that resource, so the appropriate response is to ask them to authenticate with the correct account.

---

## Part 2: Doctor dashboard and slot management

## Prompt I used

> Write the `doctor_dashboard` view. It should show all the doctor's slots and their booked appointments with basic stats (total slots, booked count, available count). Also write `slot_list`, `slot_create`, and `slot_delete` views. Delete should reject if the slot is already booked.

## What I got back

```python
@doctor_required
def doctor_dashboard(request):
    slots = AvailabilitySlot.objects.filter(doctor=request.user).select_related("doctor").order_by("date", "start_time")
    booked_appointments = Appointment.objects.filter(
        slot__doctor=request.user
    ).select_related("patient", "slot").order_by("slot__date", "slot__start_time")

    return render(request, "dashboard/doctor.html", {
        "slots": slots,
        "booked_appointments": booked_appointments,
        "total_slots": slots.count(),
        "booked_count": booked_appointments.count(),
        "available_count": slots.filter(is_booked=False).count(),
    })


@doctor_required
def slot_list(request):
    all_slots = AvailabilitySlot.objects.filter(doctor=request.user).order_by("date", "start_time")
    return render(request, "slots/slot_list.html", {"slots": all_slots})


@doctor_required
def slot_create(request):
    if request.method == "POST":
        form = SlotForm(request.POST, doctor=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Slot created successfully.")
            return redirect("slot_list")
    else:
        form = SlotForm(doctor=request.user)
    return render(request, "slots/slot_create.html", {"form": form})


@doctor_required
def slot_delete(request, pk):
    slot = get_object_or_404(AvailabilitySlot, pk=pk, doctor=request.user)
    if slot.is_booked:
        messages.error(request, "Cannot delete a booked slot.")
    else:
        slot.delete()
        messages.success(request, "Slot deleted.")
    return redirect("slot_list")
```

## What I changed after

- Split `slot_list` into upcoming and past using a `Q` filter based on current date and time — the original returned all slots with no distinction.
- Added `try/except` around `form.save()` in `slot_create` to catch `ValidationError` from the model's `clean()` method and surface it back to the form as a non-field error.

---

## Part 3: Patient dashboard with search and filtering

## Prompt I used

> Write the `patient_dashboard` view. It should show all doctors who have available upcoming slots, with a search by doctor name and a date filter. Also show the patient's own booked appointments. Avoid N+1 queries — use `annotate` and `prefetch_related`.

## What I got back

The initial version used a simple `filter()` with no annotations. Replaced it entirely with an annotated queryset approach:

```python
@patient_required
def patient_dashboard(request):
    now   = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    q        = request.GET.get('q', '').strip()
    date_str = request.GET.get('date', '').strip()

    available_slots_qs = AvailabilitySlot.objects.filter(is_booked=False)

    if date_str:
        filter_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
        available_slots_qs = available_slots_qs.filter(date=filter_date)
        if filter_date == today:
            available_slots_qs = available_slots_qs.filter(start_time__gt=current_time)
        elif filter_date < today:
            available_slots_qs = available_slots_qs.none()
    else:
        available_slots_qs = available_slots_qs.filter(
            Q(date__gt=today) | Q(date=today, start_time__gt=current_time)
        )

    doctors = User.objects.filter(role=User.ROLE_DOCTOR)
    if q:
        doctors = doctors.filter(Q(last_name__icontains=q) | Q(first_name__icontains=q))

    doctors = (
        doctors
        .annotate(available_count=Count("slots", filter=count_filter))
        .filter(available_count__gt=0)
        .order_by("last_name", "first_name")
        .prefetch_related(
            Prefetch("slots", queryset=available_slots_qs.order_by("date", "start_time"))
        )
    )

    my_appointments = Appointment.objects.filter(
        patient=request.user
    ).select_related('slot', 'slot__doctor').order_by('slot__date', 'slot__start_time')

    return render(request, "dashboard/patient.html", {
        "doctors": doctors,
        "appointments": my_appointments,
        "q": q,
        "date": date_str,
    })
```

The `annotate + prefetch_related` pattern means one query to get doctors with available slot counts, and one prefetch query to load their slots — not one query per doctor.

## What I changed after

- Built the `count_filter` Q object dynamically based on the date filter so the annotated count matches the filtered slot list shown on screen.
- Added `ValueError` handling around `strptime` so an invalid date string in the URL doesn't crash the view.

---

## Part 4: Cancel appointment view

## Prompt I used

> Write a `cancel_appointment` view. Both patients (cancelling their own) and doctors (cancelling from their side) should be able to cancel. When cancelled, the slot's `is_booked` flag should be reset to False so it becomes available again.

## What I got back

```python
@login_required
def cancel_appointment(request, pk):
    if request.method != "POST":
        return redirect("dashboard")

    if request.user.is_patient():
        appointment = get_object_or_404(Appointment, pk=pk, patient=request.user)
    else:
        appointment = get_object_or_404(Appointment, pk=pk, slot__doctor=request.user)

    slot = appointment.slot

    with transaction.atomic():
        slot.is_booked = False
        slot.save()
        appointment.delete()

    messages.success(request, "Appointment cancelled successfully. The slot is now available again.")
    return redirect("dashboard")
```

Used as-is. Wrapping in `transaction.atomic()` ensures the slot flag reset and appointment deletion either both succeed or both fail — no half-cancelled state.

---

## Part 5: Google Calendar connect/callback/disconnect views

These are the in-app OAuth views. Unlike the setup script (Log 03) which is for dev use, these are the production-facing views that let users connect their Google Calendar from within the web app.

## Prompt I used

> Write Django views for Google Calendar OAuth: a `connect` view that redirects to Google's consent screen, a `callback` view that exchanges the code for a token and saves it to `GoogleCalendarToken`, and a `disconnect` view that deletes the stored token. Use `google_auth_oauthlib.flow.Flow` with the `client_secret.json` file.

## What I got back

The core structure for all three views — the connect view builds the auth URL using `Flow.from_client_secrets_file()`, the callback fetches the token and saves it, and disconnect just deletes the DB record.

## What I changed after

- Added PKCE support: saved `flow.code_verifier` in the session during connect and restored it in the callback. Without this, the OAuth exchange can fail on stricter Google client configurations.
- Added `os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'` to allow HTTP on localhost during development — without this, the library rejects non-HTTPS redirect URIs.
- Added `try/except` around `flow.fetch_token()` in the callback with a user-facing error message, since this call hits Google's servers and can fail (network issues, expired state, mismatched redirect URI).
- Added a session expiry check in the callback — if `google_oauth_state` is missing from the session, redirect with an error rather than crashing with a `KeyError`.

---

## Part 6: sync_calendar_event_now (inline fallback)

The Celery-based `create_calendar_event_task` works when Redis is running, but in local dev without a worker, calendar events would never get created. Added a synchronous inline version that runs directly in the view after the booking transaction.

## Prompt I used

> Extract the Google Calendar event creation logic into a shared helper function that can be called both from a Celery task and directly from a view (synchronously). The view should call it inline when Celery is unavailable, so calendar events still get created in local dev.

## What I got back — pattern used

```python
def _push_calendar_event(user, doctor, patient, date_str, start_time_str, end_time_str):
    """Push a single calendar event for `user`. Returns True on success."""
    token = GoogleCalendarToken.objects.filter(user=user).first()
    if not token:
        return False
    # ... build credentials, call Google API ...

def sync_calendar_event_now(patient_id, doctor_id, date_str, start_time_str, end_time_str):
    """Synchronous inline version — safe to call directly from a view."""
    patient = User.objects.get(pk=patient_id)
    doctor  = User.objects.get(pk=doctor_id)
    created_for = []
    for user in [patient, doctor]:
        try:
            ok = _push_calendar_event(user, doctor, patient, date_str, start_time_str, end_time_str)
            if ok:
                created_for.append(user.username)
        except Exception as exc:
            logger.error("Inline calendar sync failed for %s: %s", user.username, exc)
    return created_for
```

The `_push_calendar_event` helper is shared — the Celery task calls it per-user in a loop, and `sync_calendar_event_now` calls it for both users inline. The token refresh logic (re-saving updated credentials to the DB) was also added inside this helper rather than in the task, so it works regardless of which path calls it.
