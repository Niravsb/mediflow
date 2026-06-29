# Serverless Email Service — Local Development Setup
**Tool used:** ChatGPT (GPT-4o)
**Date:** June 27, 2026

---

## Context

Wanted the email notification logic to live outside the Django app — a separate service that could eventually be deployed as AWS Lambda functions independently of the main application. Django would just POST JSON to an HTTP endpoint; it shouldn't care whether that endpoint is AWS or a local server.

The Serverless Framework handles this well in production. The local development story for Python handlers is messier — `serverless-offline` natively only runs Node.js, and getting it to invoke Python requires extra plugins and Docker. Decided to bypass that entirely.

---

## Prompt I used

> I'm building a separate email microservice using the Serverless Framework with Python. I want to test it locally alongside Django. Generate a `serverless.yml` and a basic `handler.py` for two endpoints: `/email/signup-welcome` and `/email/booking-confirmation`.

## What I got back

`serverless.yml`:

```yaml
service: hms-email-service

provider:
  name: aws
  runtime: python3.9

functions:
  signupWelcome:
    handler: handler.signup_welcome
    events:
      - http:
          path: email/signup-welcome
          method: post

  bookingConfirmation:
    handler: handler.booking_confirmation
    events:
      - http:
          path: email/booking-confirmation
          method: post

plugins:
  - serverless-offline
```

`handler.py` (stub):

```python
import json

def signup_welcome(event, context):
    body = json.loads(event.get('body', '{}'))
    return {"statusCode": 200, "body": json.dumps({"message": "Sent"})}

def booking_confirmation(event, context):
    body = json.loads(event.get('body', '{}'))
    return {"statusCode": 200, "body": json.dumps({"message": "Sent"})}
```

The `serverless.yml` was used as-is (added `cors: true` and the SMTP env vars). The handler stub was the starting point for the actual implementation.

---

## Problem: serverless-offline doesn't support Python natively

`serverless-offline` only invokes Node.js handlers. Running Python through it requires `serverless-python-requirements` plus Docker, which is too much overhead just to test two HTTP endpoints locally.

The cleaner solution: write a minimal Python HTTP server that mimics the API Gateway event structure and calls the handler functions directly. Zero extra dependencies.

## Follow-up prompt

> `serverless-offline` only runs Node.js natively. Instead, write a `local_server.py` using Python's `http.server` that listens on port 3000, wraps incoming POST bodies in a Lambda-style `event` dict, and calls the Python handlers directly. Same local URL contract as serverless-offline, no Node required.

## What I got back

```python
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from handler import signup_welcome, booking_confirmation

ROUTES = {
    "/dev/email/signup-welcome":      signup_welcome,
    "/dev/email/booking-confirmation": booking_confirmation,
}

class EmailServiceHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"

        handler_fn = ROUTES.get(self.path)
        if not handler_fn:
            self.send_response(404)
            self.end_headers()
            return

        event = {"body": raw_body}
        result = handler_fn(event, context=None)

        self.send_response(result.get("statusCode", 200))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(result.get("body", "{}").encode())

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 3000), EmailServiceHandler)
    print("Email service running at http://localhost:3000/dev")
    server.serve_forever()
```

## What I changed after

- Added a `log_message()` override to the handler class to clean up the default `http.server` access log format.
- Added startup prints showing both available endpoints so it's obvious what's running at a glance.
- Fleshed out `handler.py` with actual SMTP logic using `smtplib` — credentials come from `SMTP_USER` and `SMTP_PASS` env vars, with a graceful fallback that logs intent without crashing when credentials aren't set (standard local dev behaviour).
- Added the 404 response body to include a JSON error rather than an empty response.
