import json
import smtplib
from email.message import EmailMessage
import os


def send_email(to_email, subject, body):
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = os.environ.get('SMTP_USER', 'noreply@hms.local')
    msg['To'] = to_email

    # Standard Gmail SMTP config (requires App Password).
    # Wrap in try/except for local dev without credentials.
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(os.environ.get('SMTP_USER'), os.environ.get('SMTP_PASS'))
            server.send_message(msg)
    except Exception as e:
        print(f"SMTP skipped/failed locally. Email intent: {subject} to {to_email}")


def signup_welcome(event, context):
    body = json.loads(event.get('body', '{}'))
    email = body.get('email')
    first_name = body.get('first_name', 'User')

    text = f"Welcome to HMS, {first_name}! Your account is ready."
    send_email(email, "Welcome to HMS", text)

    return {"statusCode": 200, "body": json.dumps({"message": "Sent"})}


def booking_confirmation(event, context):
    body = json.loads(event.get('body', '{}'))

    patient_text = f"Your appointment on {body.get('date')} at {body.get('time')} is confirmed."
    doctor_text = f"New booking on {body.get('date')} at {body.get('time')}."

    send_email(body.get('patient_email'), "Appointment Confirmed", patient_text)
    send_email(body.get('doctor_email'), "New Appointment Booked", doctor_text)

    return {"statusCode": 200, "body": json.dumps({"message": "Sent"})}