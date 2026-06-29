from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import AvailabilitySlot, User


class DoctorSignupForm(UserCreationForm):
    """Registration form that automatically sets role to DOCTOR."""

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
    """Registration form that automatically sets role to PATIENT."""

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
    """Thin wrapper so views can import a consistently-named form."""
    pass


class SlotForm(forms.ModelForm):
    """
    Form for doctors to create availability slots.
    Accepts a ``doctor`` keyword argument and auto-assigns it.
    """

    class Meta:
        model = AvailabilitySlot
        fields = ('date', 'start_time', 'end_time')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
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
