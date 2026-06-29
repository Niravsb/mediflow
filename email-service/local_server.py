"""
Local dev server for the HMS email service.

Mimics the serverless-offline HTTP endpoints so the Django app
can call them at http://localhost:3000/dev/email/* during development.

Usage:
    python local_server.py
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from handler import signup_welcome, booking_confirmation

ROUTES = {
    "/dev/email/signup-welcome": signup_welcome,
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
            self.wfile.write(json.dumps({"error": "Not found"}).encode())
            return

        # Build a Lambda-like event object
        event = {"body": raw_body}
        result = handler_fn(event, context=None)

        self.send_response(result.get("statusCode", 200))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(result.get("body", "{}").encode())

    def log_message(self, fmt, *args):
        print(f"[email-service] {args[0]}")


if __name__ == "__main__":
    port = 3000
    server = HTTPServer(("127.0.0.1", port), EmailServiceHandler)
    print(f"HMS Email Service running at http://localhost:{port}/dev")
    print("  POST /dev/email/signup-welcome")
    print("  POST /dev/email/booking-confirmation")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
