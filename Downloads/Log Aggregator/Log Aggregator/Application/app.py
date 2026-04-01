# Application entry point for the Log Aggregator API.
#
# Responsibilities:
#   - Bootstrap Flask and resolve paths to sibling modules (Conversion, Dashboard).
#   - Conditionally load optional modules (log converter, dashboard blueprint).
#   - Register all route blueprints (core, payments, auth, orders, users,
#     infrastructure, simulator, dashboard).
#   - Install before/after request middleware for structured request logging.
#   - Register HTTP error handlers that return consistent JSON error payloads.
#   - Print available endpoints and start the dev server when run directly.

from flask import Flask, jsonify, request
from logger import info, error, warn
import os
import sys
import time
import threading
from dotenv import load_dotenv

# ── Directory resolution ──────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
CONVERSION_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'Conversion'))
DASHBOARD_DIR  = os.path.abspath(os.path.join(BASE_DIR, '..', 'Dashboard'))

# Load .env from the workspace root so AWS credentials and app secrets are available.
# override=True ensures refreshed .env credentials replace any stale shell/system values.
load_dotenv(os.path.abspath(os.path.join(BASE_DIR, '..', '.env')), override=True)

# ── Application Configuration ──────────────────────────────────────────────────
APP_PORT = int(os.getenv('APP_PORT', '5000'))
APP_HOST = os.getenv('APP_HOST', 'localhost')
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'true').lower() in ('true', '1', 'yes')
APP_LOG_FILENAME = os.getenv('LOG_FILENAME', 'application.log')

# Add sibling directories to sys.path so their modules can be imported directly.
for module_dir in (CONVERSION_DIR, DASHBOARD_DIR):
    if module_dir not in sys.path:
        sys.path.append(module_dir)

# ── Optional dependency flags ─────────────────────────────────────────────────
# Both the converter and dashboard are treated as optional so the app starts
# successfully even when their dependencies (reportlab, boto3, etc.) are absent.
try:
    from log_to_csv_service import convert_log_to_rows, write_rows_to_csv, write_unique_errors_json  # type: ignore[reportMissingImports]
    CONVERTER_AVAILABLE = True
except Exception:
    CONVERTER_AVAILABLE = False

try:
    from dashboard_blueprint import create_dashboard_blueprint  # type: ignore[reportMissingImports]
    DASHBOARD_AVAILABLE = True
except Exception:
    DASHBOARD_AVAILABLE = False

# ── Flask application ─────────────────────────────────────────────────────────
app = Flask(__name__)

# Debounce conversion: after a write burst, wait 2 s before regenerating artefacts.
_conversion_timer: threading.Timer | None = None
_conversion_lock = threading.Lock()
_CONVERSION_DEBOUNCE_SECONDS = 2.0


def _schedule_conversion():
    """Schedule a single deferred conversion run.
    Any call within the debounce window resets the timer."""
    global _conversion_timer
    with _conversion_lock:
        if _conversion_timer is not None:
            _conversion_timer.cancel()
        _conversion_timer = threading.Timer(_CONVERSION_DEBOUNCE_SECONDS, run_conversion_outputs)
        _conversion_timer.daemon = True
        _conversion_timer.start()


def run_conversion_outputs():
    """Parse the latest application log and regenerate the CSV and unique-errors
    JSON artefacts consumed by the dashboard."""
    if not CONVERTER_AVAILABLE:
        return

    source_log              = os.path.join(BASE_DIR, 'logs', APP_LOG_FILENAME)
    output_csv              = os.path.join(CONVERSION_DIR, 'converted_application_logs.csv')
    output_unique_errors_json = os.path.join(CONVERSION_DIR, 'unique_errors.json')

    try:
        rows = convert_log_to_rows(source_log)
        write_rows_to_csv(rows, output_csv)
        write_unique_errors_json(rows, output_unique_errors_json)
    except Exception as conversion_error:
        warn(f"Log conversion failed: {str(conversion_error)}")


# ── Blueprint registration ────────────────────────────────────────────────────
from routes.core           import core_bp
from routes.payments       import payments_bp
from routes.auth           import auth_bp
from routes.orders         import orders_bp
from routes.users          import users_bp
from routes.infrastructure import infrastructure_bp
from routes.simulator      import create_simulator_blueprint

app.register_blueprint(core_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(users_bp)
app.register_blueprint(infrastructure_bp)
# The simulator blueprint needs the log path and conversion callback at creation time.
app.register_blueprint(create_simulator_blueprint(BASE_DIR, APP_LOG_FILENAME, run_conversion_outputs))

if DASHBOARD_AVAILABLE:
    app.register_blueprint(create_dashboard_blueprint(CONVERSION_DIR, run_conversion_outputs))

# ── Middleware ────────────────────────────────────────────────────────────────

@app.before_request
def log_request():
    # Log every incoming request with its source IP address.
    info(f"{request.method} {request.path}", f"IP: {request.remote_addr}")

@app.after_request
def log_response(response):
    # Log the HTTP status code for every outgoing response, then schedule
    # a debounced conversion so the dashboard stays up-to-date without
    # blocking every request.
    info(f"{request.method} {request.path}", f"Status Code: {response.status_code}")
    _schedule_conversion()
    return response

# ── HTTP error handlers ───────────────────────────────────────────────────────
# These intercept unhandled Flask HTTP exceptions and return consistent JSON
# error payloads instead of the default HTML error pages.

@app.errorhandler(400)
def bad_request(exc):
    error_code = 4000
    error(f"Bad request: {str(exc)}", {"error_code": error_code})
    return jsonify({"error": "Bad request", "error_code": error_code}), 400

@app.errorhandler(401)
def unauthorized(exc):
    error_code = 4001
    error("Unauthorized access attempt", {"error_code": error_code})
    return jsonify({"error": "Unauthorized", "error_code": error_code}), 401

@app.errorhandler(403)
def forbidden(exc):
    error_code = 4003
    error(f"Forbidden access: {str(exc)}", {"error_code": error_code})
    return jsonify({"error": "Forbidden", "error_code": error_code}), 403

@app.errorhandler(404)
def not_found(exc):
    error_code = 4004
    warn(f"Endpoint not found: {request.method} {request.path}", {"error_code": error_code})
    return jsonify({"error": "Endpoint not found", "error_code": error_code}), 404

@app.errorhandler(405)
def method_not_allowed(exc):
    error_code = 4005
    error(f"Method not allowed: {request.method} {request.path}", {"error_code": error_code})
    return jsonify({"error": "Method not allowed", "error_code": error_code}), 405

@app.errorhandler(500)
def internal_error(exc):
    error_code = 5000
    error(f"Internal server error: {str(exc)}", {"error_code": error_code})
    return jsonify({"error": "Internal server error", "error_code": error_code}), 500

@app.errorhandler(503)
def service_unavailable(exc):
    error_code = 5003
    error(f"Service unavailable: {str(exc)}", {"error_code": error_code})
    return jsonify({"error": "Service unavailable", "error_code": error_code}), 503

# ── Dev-server entry point ────────────────────────────────────────────────────

if __name__ == '__main__':
    info("Server started successfully", f"port: {APP_PORT}, host: {APP_HOST}")
    run_conversion_outputs()
    print(f"\nAPI running at http://{APP_HOST}:{APP_PORT}")
    print("Available endpoints:")
    print("  GET  /                      - Welcome message")
    print("  GET  /api/status            - Server status")
    print("  POST /api/logs              - Submit a log entry")
    print("  GET  /api/logs              - Retrieve all logs")
    print("  GET  /dashboard             - Error analytics dashboard")
    print("  GET  /api/dashboard-data    - Dashboard JSON data")
    print("\nPayment Endpoints:")
    print("  POST /api/payments/charge           - Card declined / gateway timeout (402/503)")
    print("  POST /api/payments/refund           - Refund window expired (422)")
    print("\nAuth Endpoints:")
    print("  POST /api/auth/token                - Invalid credentials / MFA required (401)")
    print("  POST /api/auth/refresh              - JWT refresh token expired (401)")
    print("  POST /api/auth/login                - Account locked after failed attempts (429)")
    print("\nOrder Endpoints:")
    print("  POST /api/orders                    - Stock depleted (409)")
    print("  GET  /api/orders/<id>               - Order not found (404)")
    print("  DELETE /api/orders/<id>             - Order already shipped (409)")
    print("\nUser Endpoints:")
    print("  POST /api/users/register            - Email already registered (409)")
    print("  PUT  /api/users/profile             - Invalid phone number (422)")
    print("\nInfrastructure / Downstream Endpoints:")
    print("  POST /api/notifications/email       - Email service down (503)")
    print("  GET  /api/recommendations           - Upstream timeout (504)")
    print("  POST /api/inventory/sync            - Inventory service unavailable (503)")
    print("  POST /api/fulfillment/dispatch      - Bad gateway from fulfillment provider (502)")
    print("\nValidation Endpoint:")
    print("  POST /api/validate                  - Validate user data (name, email, age)")
    print("\nTraffic Simulator:")
    print("  POST /api/simulate-traffic          - Seed 215 realistic backdated error events\n")

    app.run(debug=FLASK_DEBUG, port=APP_PORT, host=APP_HOST)
