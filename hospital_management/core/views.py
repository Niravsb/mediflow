import json
import logging
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.conf import settings

from .decorators import doctor_required, patient_required
from .forms import DoctorSignupForm, LoginForm, PatientSignupForm, SlotForm
from .models import AvailabilitySlot, User, Appointment, GoogleCalendarToken
from .services import (
    trigger_booking_email_task,
    trigger_signup_welcome_email_task,
    create_calendar_event_task,
    sync_calendar_event_now,
)

logger = logging.getLogger(__name__)


# --- Auth Views ---
def signup_doctor(request):
    if request.user.is_authenticated: return redirect("dashboard")
    if request.method == "POST":
        form = DoctorSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, Dr. {user.last_name}!")
            try:
                trigger_signup_welcome_email_task.delay(email=user.email, first_name=user.first_name)
            except Exception:
                logger.warning("Signup welcome email dispatch failed (broker down?)")
            return redirect("doctor_dashboard")
    else:
        form = DoctorSignupForm()
    return render(request, "auth/signup_doctor.html", {"form": form})


def signup_patient(request):
    if request.user.is_authenticated: return redirect("dashboard")
    if request.method == "POST":
        form = PatientSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.first_name}!")
            try:
                trigger_signup_welcome_email_task.delay(email=user.email, first_name=user.first_name)
            except Exception:
                logger.warning("Signup welcome email dispatch failed (broker down?)")
            return redirect("patient_dashboard")
    else:
        form = PatientSignupForm()
    return render(request, "auth/signup_patient.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated: return redirect("dashboard")
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("doctor_dashboard" if user.is_doctor() else "patient_dashboard")
    else:
        form = LoginForm(request)
    return render(request, "auth/login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect("login")


# --- Dashboards ---
@login_required
def dashboard(request):
    return redirect("doctor_dashboard" if request.user.is_doctor() else "patient_dashboard")


@doctor_required
def doctor_dashboard(request):
    slots = AvailabilitySlot.objects.filter(doctor=request.user).select_related("doctor").order_by("date", "start_time")
    
    # Get booked appointments for this doctor
    booked_appointments = Appointment.objects.filter(
        slot__doctor=request.user
    ).select_related("patient", "slot").order_by("slot__date", "slot__start_time")

    total_slots = slots.count()
    booked_count = booked_appointments.count()
    available_count = slots.filter(is_booked=False).count()

    return render(request, "dashboard/doctor.html", {
        "slots": slots,
        "booked_appointments": booked_appointments,
        "total_slots": total_slots,
        "booked_count": booked_count,
        "available_count": available_count,
    })



@patient_required
def patient_dashboard(request):
    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    q = request.GET.get('q', '').strip()
    date_str = request.GET.get('date', '').strip()

    available_slots_qs = AvailabilitySlot.objects.filter(is_booked=False)

    # Filter available slots by date if provided
    if date_str:
        try:
            filter_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
            available_slots_qs = available_slots_qs.filter(date=filter_date)
            if filter_date == today:
                available_slots_qs = available_slots_qs.filter(start_time__gt=current_time)
            elif filter_date < today:
                available_slots_qs = available_slots_qs.none()
        except ValueError:
            pass
    else:
        # Default upcoming filter
        available_slots_qs = available_slots_qs.filter(
            Q(date__gt=today) | Q(date=today, start_time__gt=current_time)
        )

    # Build dynamically matching count filter
    if date_str:
        try:
            filter_date = timezone.datetime.strptime(date_str, "%Y-%m-%d").date()
            if filter_date == today:
                count_filter = Q(slots__is_booked=False, slots__date=filter_date, slots__start_time__gt=current_time)
            else:
                count_filter = Q(slots__is_booked=False, slots__date=filter_date)
        except ValueError:
            count_filter = Q(slots__is_booked=False) & (
                Q(slots__date__gt=today) | Q(slots__date=today, slots__start_time__gt=current_time)
            )
    else:
        count_filter = Q(slots__is_booked=False) & (
            Q(slots__date__gt=today) | Q(slots__date=today, slots__start_time__gt=current_time)
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

    my_appointments = Appointment.objects.filter(patient=request.user).select_related('slot', 'slot__doctor').order_by('slot__date', 'slot__start_time')

    return render(request, "dashboard/patient.html", {
        "doctors": doctors,
        "appointments": my_appointments,
        "q": q,
        "date": date_str,
    })



# --- Slot Management ---
@doctor_required
def slot_list(request):
    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    all_slots = AvailabilitySlot.objects.filter(doctor=request.user).order_by("date", "start_time")
    
    upcoming = all_slots.filter(
        Q(date__gt=today) | Q(date=today, start_time__gt=current_time)
    )
    past = all_slots.exclude(
        Q(date__gt=today) | Q(date=today, start_time__gt=current_time)
    )

    return render(request, "slots/slot_list.html", {
        "upcoming": upcoming,
        "past": past,
    })


@doctor_required
def slot_create(request):
    if request.method == "POST":
        form = SlotForm(request.POST, doctor=request.user)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, "Slot created successfully.")
                return redirect("slot_list")
            except Exception as exc:
                form.add_error(None, str(exc))
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


# --- Booking Logic (Atomic Transaction) ---
@patient_required
def book_slot(request, pk):
    if request.method != "POST":
        return redirect("patient_dashboard")

    notes = request.POST.get('notes', '').strip()

    try:
        with transaction.atomic():
            slot = AvailabilitySlot.objects.select_for_update().get(pk=pk)

            if slot.is_booked:
                messages.error(request, "Sorry, this slot was just booked by someone else.")
                return redirect("patient_dashboard")

            slot.is_booked = True
            slot.save()
            Appointment.objects.create(patient=request.user, slot=slot, notes=notes)

            messages.success(request, f"Successfully booked appointment with Dr. {slot.doctor.last_name}!")

    except AvailabilitySlot.DoesNotExist:
        messages.error(request, "Slot not found.")
        return redirect("patient_dashboard")

    # ── Fire async tasks (best-effort email) ────────────────────────────────
    try:
        trigger_booking_email_task.delay(
            patient_email=request.user.email,
            doctor_email=slot.doctor.email,
            date_str=str(slot.date),
            time_str=str(slot.start_time),
        )
    except Exception as exc:
        logger.warning("Email task dispatch failed (broker down?): %s", exc)

    # ── Google Calendar sync (synchronous — no Celery worker needed) ─────────
    try:
        synced_for = sync_calendar_event_now(
            patient_id=request.user.id,
            doctor_id=slot.doctor.id,
            date_str=str(slot.date),
            start_time_str=str(slot.start_time),
            end_time_str=str(slot.end_time),
        )
        if synced_for:
            messages.info(request, f"📅 Calendar event added for: {', '.join(synced_for)}")
        else:
            messages.info(
                request,
                "📅 Tip: <a href='/calendar/connect/'>Connect your Google Calendar</a> "
                "to automatically add appointments.",
            )
    except Exception as exc:
        logger.warning("Inline calendar sync failed: %s", exc)

    return redirect("patient_dashboard")


@login_required
def cancel_appointment(request, pk):
    """Cancel appointment and release the availability slot."""
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



# --- Google Calendar OAuth ---

GOOGLE_SCOPES = ['https://www.googleapis.com/auth/calendar.events']


@login_required
def google_calendar_connect(request):
    """Step 1 — redirect the user to Google's OAuth consent screen."""
    import os
    from google_auth_oauthlib.flow import Flow

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # allow http on localhost

    client_secret_path = settings.BASE_DIR / 'client_secret.json'
    flow = Flow.from_client_secrets_file(
        str(client_secret_path),
        scopes=GOOGLE_SCOPES,
        redirect_uri=request.build_absolute_uri('/calendar/callback/'),
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    # ── PKCE: persist the code_verifier so the callback can send it back ──
    request.session['google_oauth_state']         = state
    request.session['google_oauth_code_verifier'] = flow.code_verifier
    request.session.modified = True
    return redirect(auth_url)


@login_required
def google_calendar_callback(request):
    """Step 2 — Google redirects here with ?code=...  Save the token."""
    import os
    from google_auth_oauthlib.flow import Flow

    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # allow http on localhost

    state = request.session.get('google_oauth_state')
    if not state:
        messages.error(request, 'OAuth session expired. Please try again.')
        return redirect('dashboard')

    client_secret_path = settings.BASE_DIR / 'client_secret.json'
    flow = Flow.from_client_secrets_file(
        str(client_secret_path),
        scopes=GOOGLE_SCOPES,
        state=state,
        redirect_uri=request.build_absolute_uri('/calendar/callback/'),
    )

    # ── PKCE: restore the code_verifier that was saved in the connect step ──
    code_verifier = request.session.get('google_oauth_code_verifier')
    if code_verifier:
        flow.code_verifier = code_verifier

    try:
        flow.fetch_token(authorization_response=request.build_absolute_uri())
    except Exception as exc:
        logger.error('Google OAuth callback failed: %s', exc)
        messages.error(request, f'Google authentication failed: {exc}')
        return redirect('dashboard')

    creds = flow.credentials
    token_data = {
        'token':          creds.token,
        'refresh_token':  creds.refresh_token,
        'token_uri':      creds.token_uri,
        'client_id':      creds.client_id,
        'client_secret':  creds.client_secret,
        'scopes':         list(creds.scopes),
    }

    GoogleCalendarToken.objects.update_or_create(
        user=request.user,
        defaults={'credentials': token_data},
    )
    messages.success(request, '✅ Google Calendar connected successfully!')
    return redirect('dashboard')


@login_required
def google_calendar_disconnect(request):
    """Remove the stored Google Calendar token for this user."""
    if request.method == 'POST':
        GoogleCalendarToken.objects.filter(user=request.user).delete()
        messages.success(request, 'Google Calendar disconnected.')
    return redirect('dashboard')