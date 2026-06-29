# Architecture & Data Model Design
**Tool used:** Claude 3.5 Sonnet
**Date:** June 25, 2026

---

## Context

Needed to decide how to model doctors and patients in Django. The two obvious approaches were multi-table inheritance (separate Doctor/Patient tables) or a single user model with a role field. Went with the role field approach since it avoids extra joins on every auth check — every request hits the user table, so keeping it lean matters.

## Prompt I used

> I'm designing a hospital management system in Django. I need authentication for both Doctors and Patients. What's the cleanest way to do this without the performance overhead of multi-table inheritance or OneToOne profile tables just for basic auth checks?

## What I got back

Claude confirmed the `AbstractUser` + `role` field pattern and gave a clean starting implementation:

```python
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_DOCTOR  = "DOCTOR"
    ROLE_PATIENT = "PATIENT"
    ROLE_CHOICES = [
        (ROLE_DOCTOR,  "Doctor"),
        (ROLE_PATIENT, "Patient"),
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_PATIENT)

    def is_doctor(self):
        return self.role == self.ROLE_DOCTOR

    def is_patient(self):
        return self.role == self.ROLE_PATIENT
```

Used this as the base and added `get_full_name_or_username()` myself later.

---

## Follow-up: AvailabilitySlot and Appointment models

Already had a clear idea for the slot model — wanted `is_booked` as an explicit boolean rather than checking `hasattr(slot, 'appointment')`. The reason: I knew I'd need `select_for_update()` to prevent race conditions during booking, and locking on a concrete boolean column on the slot row itself is much cleaner than locking on the presence/absence of a related record.

## Prompt I used

> For `AvailabilitySlot`, I want to use an explicit `is_booked` boolean rather than deriving booked status from the existence of an `Appointment`. I need `select_for_update()` row-level locking during booking to prevent double-bookings. Write the `AvailabilitySlot` and `Appointment` models — slots tied to doctors, appointments tied to patients.

## What I got back

```python
class AvailabilitySlot(models.Model):
    doctor = models.ForeignKey(
        "core.User",
        on_delete=models.CASCADE,
        related_name="slots",
        limit_choices_to={"role": User.ROLE_DOCTOR},
    )
    date       = models.DateField()
    start_time = models.TimeField()
    end_time   = models.TimeField()
    is_booked  = models.BooleanField(default=False)

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time.")

        overlapping = AvailabilitySlot.objects.filter(
            doctor=self.doctor,
            date=self.date,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(pk=self.pk)

        if overlapping.exists():
            raise ValidationError("This overlaps with an existing slot.")

    class Meta:
        ordering = ["date", "start_time"]


class Appointment(models.Model):
    patient = models.ForeignKey(
        "core.User",
        on_delete=models.CASCADE,
        related_name="appointments",
        limit_choices_to={"role": "PATIENT"}
    )
    slot = models.OneToOneField(
        "core.AvailabilitySlot",
        on_delete=models.CASCADE,
        related_name="appointment"
    )
    created_at = models.DateTimeField(auto_now_add=True)
```

## What I changed after

- Added past-date and past-time validation inside `clean()` — the AI version didn't block doctors from creating slots in the past.
- Overrode `save()` to call `full_clean()` so the overlap check is enforced even on direct model saves (not just form submissions).
- Added a `notes` field on `Appointment` for patient symptom descriptions.
- Added the `is_available` property for template-level display logic.
