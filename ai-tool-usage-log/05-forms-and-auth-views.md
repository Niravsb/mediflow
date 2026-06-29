# Forms and Authentication Views
**Tool used:** Claude 3.5 Sonnet
**Date:** June 25, 2026

---

## Context

Needed signup forms for both doctors and patients. The key requirement was that the role field should never be exposed to the user — a patient shouldn't be able to sign up as a doctor just by changing a form field. The role has to be set by the form itself based on which signup page the user is on.

Also needed a login form and the corresponding views to wire everything together with Django's auth system.

---

## Prompt I used

> I have a custom `User` model with a `role` field (DOCTOR or PATIENT). I need two separate signup forms — one that auto-sets role to DOCTOR, one that auto-sets role to PATIENT. The role field should not be visible or editable by the user. Both forms should collect username, first name, last name, email, and password. Use `UserCreationForm` as the base.

## What I got back

```python
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from .models import AvailabilitySlot, User


class DoctorSignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_DOCTOR
        if commit:
            user.save()
        return user


class PatientSignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_PATIENT
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    pass
```

Used exactly as provided. The `commit=False` pattern lets us set the role before the DB write, which is the correct approach — avoids a two-step save.

---

## Follow-up: SlotForm

Doctors create availability slots through a form. The `doctor` field on `AvailabilitySlot` should be auto-assigned from `request.user` — doctors shouldn't see or pick a doctor from a dropdown.

## Prompt I used

> Write a `ModelForm` for `AvailabilitySlot` that only shows `date`, `start_time`, and `end_time` fields. It should accept a `doctor` keyword argument in `__init__` and auto-assign it on save, so the doctor field is never part of the form UI.

## What I got back

```python
class SlotForm(forms.ModelForm):
    class Meta:
        model = AvailabilitySlot
        fields = ('date', 'start_time', 'end_time')
        widgets = {
            'date':       forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time':   forms.TimeInput(attrs={'type': 'time'}),
        }

    def __init__(self, *args, doctor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctor = doctor
        if doctor:
            self.instance.doctor = doctor

    def save(self, commit=True):
        slot = super().save(commit=False)
        slot.doctor = self.doctor
        if commit:
            slot.save()
        return slot
```

Used as-is. Setting `self.instance.doctor = doctor` in `__init__` means validation in `clean()` (specifically the overlap check) already has access to the doctor even before `save()` is called.

---

## Auth views

## Prompt I used

> Write the `signup_doctor`, `signup_patient`, `login_view`, and `logout_view` views. Signup views should redirect already-authenticated users. On successful signup, log the user in immediately and redirect to their dashboard. On successful login, redirect to the appropriate dashboard based on role.

## What I got back

```python
def signup_doctor(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = DoctorSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, Dr. {user.last_name}!")
            return redirect("doctor_dashboard")
    else:
        form = DoctorSignupForm()
    return render(request, "auth/signup_doctor.html", {"form": form})


def signup_patient(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = PatientSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.first_name}!")
            return redirect("patient_dashboard")
    else:
        form = PatientSignupForm()
    return render(request, "auth/signup_patient.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
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
```

## What I changed after

- Added the `trigger_signup_welcome_email_task.delay()` call inside both signup views, wrapped in try/except so a broker failure doesn't block the signup redirect.
- The email dispatch was not in the original — it was added once the email service (Log 04) was in place.
