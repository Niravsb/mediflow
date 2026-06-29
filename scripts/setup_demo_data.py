"""
Demo data setup script.
Run with: python manage.py shell < scripts/setup_demo_data.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hospital_management.settings')
django.setup()

from hospital_management.core.models import User, AvailabilitySlot
import datetime

print("=== Setting up demo data ===")

# Create doctor
doctor, created = User.objects.get_or_create(
    username='dr_smith',
    defaults={
        'first_name': 'John',
        'last_name': 'Smith',
        'email': 'dr.smith@hospital.com',
        'role': User.ROLE_DOCTOR,
    }
)
if created:
    doctor.set_password('doctor123')
    doctor.save()
    print(f"✓ Created doctor: {doctor} (password: doctor123)")
else:
    print(f"✓ Doctor already exists: {doctor}")

# Create patient
patient, created = User.objects.get_or_create(
    username='patient_alice',
    defaults={
        'first_name': 'Alice',
        'last_name': 'Johnson',
        'email': 'alice@example.com',
        'role': User.ROLE_PATIENT,
    }
)
if created:
    patient.set_password('patient123')
    patient.save()
    print(f"✓ Created patient: {patient} (password: patient123)")
else:
    print(f"✓ Patient already exists: {patient}")

# Create availability slot on July 10, 2026
slot_date = datetime.date(2026, 7, 10)
slot_start = datetime.time(10, 0)
slot_end = datetime.time(10, 30)

existing_slot = AvailabilitySlot.objects.filter(
    doctor=doctor,
    date=slot_date,
    start_time=slot_start
).first()

if not existing_slot:
    try:
        slot = AvailabilitySlot(
            doctor=doctor,
            date=slot_date,
            start_time=slot_start,
            end_time=slot_end,
        )
        slot.full_clean()
        slot.save()
        print(f"✓ Created slot: {slot}")
    except Exception as e:
        print(f"✗ Could not create slot: {e}")
else:
    print(f"✓ Slot already exists: {existing_slot}")

# Second slot
slot_start2 = datetime.time(11, 0)
slot_end2 = datetime.time(11, 30)
existing_slot2 = AvailabilitySlot.objects.filter(
    doctor=doctor,
    date=slot_date,
    start_time=slot_start2
).first()
if not existing_slot2:
    try:
        slot2 = AvailabilitySlot(
            doctor=doctor,
            date=slot_date,
            start_time=slot_start2,
            end_time=slot_end2,
        )
        slot2.full_clean()
        slot2.save()
        print(f"✓ Created slot: {slot2}")
    except Exception as e:
        print(f"✗ Could not create second slot: {e}")
else:
    print(f"✓ Slot 2 already exists: {existing_slot2}")

print("\n=== Demo accounts ===")
print("Doctor  → username: dr_smith    | password: doctor123")
print("Patient → username: patient_alice | password: patient123")
print("\nVisit http://127.0.0.1:8000 and log in as patient_alice to book the July 10 slot.")
