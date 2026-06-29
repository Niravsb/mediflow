from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import models

class User(AbstractUser):
    ROLE_DOCTOR  = "DOCTOR"
    ROLE_PATIENT = "PATIENT"
    ROLE_CHOICES = [
        (ROLE_DOCTOR,  "Doctor"),
        (ROLE_PATIENT, "Patient"),
    ]

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default=ROLE_PATIENT,
        help_text="Determines which dashboard and features this user can access.",
    )

    def is_doctor(self):
        return self.role == self.ROLE_DOCTOR

    def is_patient(self):
        return self.role == self.ROLE_PATIENT

    def get_full_name_or_username(self):
        full = super().get_full_name()
        return full if full.strip() else self.username

    def __str__(self):
        return f"{self.username} ({self.role})"

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
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError({"end_time": "End time must be strictly after start time."})

        # Past date and time validation
        now = timezone.localtime(timezone.now())
        today = now.date()
        current_time = now.time()

        is_new = self.pk is None
        is_time_changed = False
        if self.pk:
            try:
                orig = AvailabilitySlot.objects.get(pk=self.pk)
                if orig.date != self.date or orig.start_time != self.start_time:
                    is_time_changed = True
            except AvailabilitySlot.DoesNotExist:
                pass

        if is_new or is_time_changed:
            if self.date:
                if self.date < today:
                    raise ValidationError({"date": "Cannot create or move availability slots to the past."})
                if self.date == today and self.start_time and self.start_time <= current_time:
                    raise ValidationError({"start_time": "Start time cannot be in the past."})

        if self.date and self.start_time and self.end_time:
            overlapping = AvailabilitySlot.objects.filter(
                doctor=self.doctor,
                date=self.date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)

            if overlapping.exists():
                raise ValidationError("This time window overlaps with one of your existing slots on the same date.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_available(self):
        if self.is_booked:
            return False
        now = timezone.localtime(timezone.now())
        today = now.date()
        current_time = now.time()
        if self.date < today:
            return False
        if self.date == today and self.start_time <= current_time:
            return False
        return True

    def __str__(self):
        status = "booked" if self.is_booked else "free"
        return f"Dr. {self.doctor.last_name} — {self.date} {self.start_time}–{self.end_time} [{status}]"

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
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Reason for appointment / symptoms description"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.patient.last_name} with {self.slot.doctor.last_name} on {self.slot.date}"



class GoogleCalendarToken(models.Model):
    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="calendar_token")
    credentials = models.JSONField(help_text="Stores the full Google OAuth credentials JSON.")