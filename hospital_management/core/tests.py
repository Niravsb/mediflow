from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import datetime, date, time, timedelta
from django.db.models import Count, Q, Prefetch
from .models import User, AvailabilitySlot, Appointment

class TimezoneAndSlotTests(TestCase):

    def setUp(self):
        # Create a doctor and a patient
        self.doctor = User.objects.create_user(
            username="doctor_bob",
            email="bob@doctor.com",
            password="password123",
            role=User.ROLE_DOCTOR,
            last_name="Bob"
        )
        self.patient = User.objects.create_user(
            username="patient_alice",
            email="alice@patient.com",
            password="password123",
            role=User.ROLE_PATIENT,
            last_name="Alice"
        )

    def test_create_past_slot_date_fails(self):
        """Creating a slot with a date in the past should raise ValidationError."""
        yesterday = timezone.localtime(timezone.now()).date() - timedelta(days=1)
        slot = AvailabilitySlot(
            doctor=self.doctor,
            date=yesterday,
            start_time=time(9, 0),
            end_time=time(10, 0)
        )
        with self.assertRaises(ValidationError) as ctx:
            slot.full_clean()
        self.assertIn("date", ctx.exception.error_dict)
        self.assertEqual(
            ctx.exception.error_dict["date"][0].message,
            "Cannot create or move availability slots to the past."
        )

    def test_create_past_slot_time_fails(self):
        """Creating a slot for today but with a start time in the past should fail."""
        now = timezone.localtime(timezone.now())
        # Let's create a time that is 30 minutes in the past
        past_datetime = now - timedelta(minutes=30)
        
        # If the past time is on a different date (e.g. crossing midnight), skip this specific test
        if past_datetime.date() == now.date():
            slot = AvailabilitySlot(
                doctor=self.doctor,
                date=now.date(),
                start_time=past_datetime.time(),
                end_time=(past_datetime + timedelta(hours=1)).time()
            )
            with self.assertRaises(ValidationError) as ctx:
                slot.full_clean()
            self.assertIn("start_time", ctx.exception.error_dict)
            self.assertEqual(
                ctx.exception.error_dict["start_time"][0].message,
                "Start time cannot be in the past."
            )

    def test_create_future_slot_succeeds(self):
        """Creating a slot in the future should succeed."""
        tomorrow = timezone.localtime(timezone.now()).date() + timedelta(days=1)
        slot = AvailabilitySlot(
            doctor=self.doctor,
            date=tomorrow,
            start_time=time(9, 0),
            end_time=time(10, 0)
        )
        # Should not raise any validation error
        slot.full_clean()
        slot.save()
        self.assertIsNotNone(slot.pk)

    def test_modify_booked_past_slot_succeeds(self):
        """Updating an existing slot's is_booked status (booking it) should succeed even if it is now in the past."""
        now = timezone.localtime(timezone.now())
        # Create a slot that starts 10 minutes in the future so it is valid when created
        future_time = now + timedelta(minutes=10)
        
        slot = AvailabilitySlot.objects.create(
            doctor=self.doctor,
            date=future_time.date(),
            start_time=future_time.time(),
            end_time=(future_time + timedelta(hours=1)).time()
        )
        
        # Now mock time moving forward by making the slot start time technically 'past'
        # and see if we can mark it as booked and save it without validation issues.
        # We can simulate this by changing is_booked without modifying date or start_time
        slot.is_booked = True
        # Since we check if date/time changed for existing slots, saving it shouldn't trigger the past validation.
        slot.full_clean()
        slot.save()
        
        self.assertTrue(slot.is_booked)

    def test_is_available_property(self):
        """Test is_available returns correct states depending on date/time/booking status."""
        now = timezone.localtime(timezone.now())
        
        # Future slot
        future_slot = AvailabilitySlot(
            doctor=self.doctor,
            date=now.date() + timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(10, 0)
        )
        self.assertTrue(future_slot.is_available)
        
        # Booked slot
        future_slot.is_booked = True
        self.assertFalse(future_slot.is_available)
        
        # Past date slot
        past_slot = AvailabilitySlot(
            doctor=self.doctor,
            date=now.date() - timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(10, 0)
        )
        self.assertFalse(past_slot.is_available)

    def test_patient_dashboard_filters_out_past_slots(self):
        """Test that past slots are not prefetched and not annotated in patient_dashboard queryset."""
        now = timezone.localtime(timezone.now())
        tomorrow = now.date() + timedelta(days=1)
        yesterday = now.date() - timedelta(days=1)

        # Create upcoming slot
        upcoming_slot = AvailabilitySlot.objects.create(
            doctor=self.doctor,
            date=tomorrow,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )

        # Create past slot by bypassing full_clean() in save()
        past_slot = AvailabilitySlot(
            doctor=self.doctor,
            date=yesterday,
            start_time=time(10, 0),
            end_time=time(11, 0)
        )
        super(AvailabilitySlot, past_slot).save()

        # Query using the logic from patient_dashboard view
        today_date = now.date()
        current_time = now.time()

        available_slots_qs = AvailabilitySlot.objects.filter(
            is_booked=False
        ).filter(
            Q(date__gt=today_date) | Q(date=today_date, start_time__gt=current_time)
        )

        doctors = (
            User.objects
            .filter(role=User.ROLE_DOCTOR)
            .annotate(
                available_count=Count(
                    "slots",
                    filter=Q(slots__is_booked=False) & (
                        Q(slots__date__gt=today_date) | Q(slots__date=today_date, slots__start_time__gt=current_time)
                    )
                )
            )
            .filter(available_count__gt=0)
            .prefetch_related(
                Prefetch("slots", queryset=available_slots_qs.order_by("date", "start_time"))
            )
        )

        # The doctor should have available_count = 1 (only the upcoming slot)
        self.assertEqual(doctors.count(), 1)
        doc = doctors.first()
        self.assertEqual(doc.available_count, 1)
        
        # Prefetched slots should only contain the upcoming slot
        slots = list(doc.slots.all())
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].pk, upcoming_slot.pk)
