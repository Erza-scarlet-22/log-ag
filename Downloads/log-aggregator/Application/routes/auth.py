# Simulated authentication API routes.
#
# These endpoints always return error responses to produce representative log
# events for dashboard testing and demonstration purposes.
#
# Routes:
#   POST /api/auth/token    — Invalid credentials (401) or MFA required (401).
#   POST /api/auth/refresh  — Expired JWT refresh token (401).
#   POST /api/auth/login    — Account locked after repeated failures (429).

from flask import Blueprint, jsonify, request
try:
    from ..logger import error, warn  # type: ignore[reportMissingImports]
except ImportError:
    from logger import error, warn  # type: ignore[reportMissingImports]

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/auth/token', methods=['POST'])
def auth_token():
    data = request.get_json() or {}

    # Allow callers to trigger the MFA scenario via a simulate flag.
    if data.get('simulate') == 'mfa_required':
        warn("MFA verification required but not provided",
             {"error_code": 6003, "user_id": "usr_8821"})
        return jsonify({"error": "MFA required", "error_code": 6003}), 401

    # Default scenario: wrong credentials supplied.
    error("Authentication failed — invalid credentials provided",
          {"error_code": 6001, "attempts": 1})
    return jsonify({"error": "Invalid credentials", "error_code": 6001}), 401


@auth_bp.route('/api/auth/refresh', methods=['POST'])
def auth_refresh():
    error("JWT refresh token has expired",
          {"error_code": 6002, "expired_at": "2026-03-28T10:00:00"})
    return jsonify({"error": "Refresh token expired", "error_code": 6002}), 401


@auth_bp.route('/api/auth/login', methods=['POST'])
def auth_login():
    error("Account temporarily locked after 5 consecutive failed login attempts",
          {"error_code": 6004, "locked_until": "2026-03-31T13:30:00", "user_id": "usr_4491"})
    return jsonify({"error": "Account locked", "error_code": 6004}), 429
