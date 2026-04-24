# Simulated user management API routes.
#
# These endpoints always return error responses to produce representative log
# events for dashboard testing and demonstration purposes.
#
# Routes:
#   POST /api/users/register — Email already registered (409).
#   PUT  /api/users/profile  — Invalid phone number format (422).

from flask import Blueprint, jsonify, request
try:
    from ..logger import error  # type: ignore[reportMissingImports]
except ImportError:
    from logger import error  # type: ignore[reportMissingImports]

users_bp = Blueprint('users', __name__)


@users_bp.route('/api/users/register', methods=['POST'])
def register_user():
    data = request.get_json() or {}
    email = data.get('email', 'user@example.com')
    error("Registration failed — email address already registered",
          {"error_code": 8001, "email": email})
    return jsonify({"error": "Email already registered", "error_code": 8001}), 409


@users_bp.route('/api/users/profile', methods=['PUT'])
def update_profile():
    error("Phone number format is invalid for the specified region",
          {"error_code": 8002, "field": "phone", "region": "US"})
    return jsonify({"error": "Invalid phone number", "error_code": 8002}), 422
