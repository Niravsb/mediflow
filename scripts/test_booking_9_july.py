import os
import sys
import django
from datetime import date, time, timedelta

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hospital_management.settings')
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.db import transaction
from django.core.exceptions import ValidationError
from hospital_management.core.models import User, AvailabilitySlot, Appointment

def run_test():
    print("=== STARTING BOOKING SYSTEM TEST FOR 9 JULY 2026 ===")
    
    # 1. Fetch Doctor (nirav)
    try:
        doctor = User.objects.get(username="nirav", role=User.ROLE_DOCTOR)
        print(f"Found doctor: Dr. {doctor.last_name} ({doctor.username})")
    except User.DoesNotExist:
        print("Doctor 'nirav' not found, creating doctor...")
        doctor = User.objects.create_user(
            username="nirav",
            email="nirav@hospital.com",
            password="testpassword123",
            role=User.ROLE_DOCTOR,
            first_name="Nirav",
            last_name="Doctor"
        )
        print(f"Created doctor: Dr. {doctor.last_name}")

    # 2. Fetch Patient (borde)
    try:
        patient = User.objects.get(username="borde", role=User.ROLE_PATIENT)
        print(f"Found patient: {patient.first_name} {patient.last_name} ({patient.username})")
    except User.DoesNotExist:
        print("Patient 'borde' not found, creating patient...")
        patient = User.objects.create_user(
            username="borde",
            email="borde@patient.com",
            password="testpassword123",
            role=User.ROLE_PATIENT,
            first_name="Borde",
            last_name="Patient"
        )
        print(f"Created patient: {patient.first_name} {patient.last_name}")

    # 3. Define target date and time range for July 9, 2026
    target_date = date(2026, 7, 9)
    # Let's find an available slot that is NOT booked yet, or create one at a new time (e.g. 14:00 - 15:00)
    start_time = time(14, 0)
    end_time = time(15, 0)

    # Clean up any existing unbooked/booked slot in this specific time range to make the test clean and reproducible
    existing_slots = AvailabilitySlot.objects.filter(
        doctor=doctor,
        date=target_date,
        start_time=start_time,
        end_time=end_time
    )
    if existing_slots.exists():
        print(f"Cleaning up {existing_slots.count()} existing slots in the 14:00-15:00 window for July 9, 2026...")
        # Delete associated appointments first to prevent CASCADE issues or just to be safe
        Appointment.objects.filter(slot__in=existing_slots).delete()
        existing_slots.delete()

    # 4. Create Availability Slot
    print(f"Creating a new availability slot for Dr. {doctor.last_name} on {target_date} from {start_time} to {end_time}...")
    try:
        slot = AvailabilitySlot(
            doctor=doctor,
            date=target_date,
            start_time=start_time,
            end_time=end_time,
            is_booked=False
        )
        slot.full_clean()
        slot.save()
        print(f"Successfully created slot (ID: {slot.id})")
    except ValidationError as e:
        print(f"ValidationError during slot creation: {e}")
        return False

    # 5. Book the slot using the database transaction logic
    print("Attempting to book the newly created slot...")
    try:
        with transaction.atomic():
            # Select slot for update to avoid race conditions
            locked_slot = AvailabilitySlot.objects.select_for_update().get(pk=slot.id)
            
            if locked_slot.is_booked:
                print("Error: Slot is already booked.")
                return False
            
            # Perform booking
            locked_slot.is_booked = True
            locked_slot.save()
            
            appointment = Appointment.objects.create(patient=patient, slot=locked_slot)
            print(f"Successfully created Appointment (ID: {appointment.id}) for patient {patient.username}!")
            
    except Exception as e:
        print(f"An error occurred during transaction booking: {e}")
        return False

    # 6. Verify booking in DB
    slot.refresh_from_db()
    print(f"Verifying slot state in database: is_booked = {slot.is_booked}")
    
    try:
        appointment_in_db = Appointment.objects.get(slot=slot)
        print(f"Verifying appointment in database: {appointment_in_db}")
        print("Verification: SUCCESS!")
    except Appointment.DoesNotExist:
        print("Verification: FAILED! Appointment not found in database.")
        return False

    # 7. Test Double Booking Prevention
    print("Testing double-booking prevention...")
    try:
        with transaction.atomic():
            locked_slot_again = AvailabilitySlot.objects.select_for_update().get(pk=slot.id)
            if locked_slot_again.is_booked:
                print("Double-booking prevented: Slot is already booked (as expected).")
                double_booking_prevented = True
            else:
                print("Double-booking failed to be prevented!")
                double_booking_prevented = False
    except Exception as e:
        print(f"Error during double booking test: {e}")
        double_booking_prevented = False

    if double_booking_prevented:
        print("=== ALL TESTS PASSED SUCCESSFULLY! ===")
        return True
    else:
        print("=== TEST FAILED! ===")
        return False

if __name__ == '__main__':
    run_test()
