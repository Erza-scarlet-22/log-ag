# Simulated downstream / infrastructure API routes.
#
# These endpoints always return error responses to produce representative log
# events covering third-party service failures and upstream timeouts.
#
# Routes:
#   POST /api/notifications/email  — Email delivery service unreachable (503).
#   GET  /api/recommendations      — Upstream recommendation engine timeout (504).
#   POST /api/inventory/sync       — Inventory microservice unreachable (503).
#   POST /api/fulfillment/dispatch — Malformed response from fulfillment provider (502).

from flask import Blueprint, jsonify
try:
    from ..logger import error  # type: ignore[reportMissingImports]
except ImportError:
    from logger import error  # type: ignore[reportMissingImports]

infrastructure_bp = Blueprint('infrastructure', __name__)


@infrastructure_bp.route('/api/notifications/email', methods=['POST'])
def send_notification():
    error("Email delivery service is unreachable — circuit breaker open",
          {"error_code": 9001, "provider": "SendGrid", "retry_after": 60})
    return jsonify({"error": "Email service unavailable", "error_code": 9001}), 503


@infrastructure_bp.route('/api/recommendations', methods=['GET'])
def get_recommendations():
    error("Upstream recommendation engine timed out after 3000ms",
          {"error_code": 9002, "service": "RecommendationEngine", "timeout_ms": 3000})
    return jsonify({"error": "Upstream timeout", "error_code": 9002}), 504


@infrastructure_bp.route('/api/inventory/sync', methods=['POST'])
def inventory_sync():
    error("Inventory microservice is unreachable — health check failed",
          {"error_code": 9003, "service": "InventoryService", "last_healthy": "2026-03-31T10:15:00"})
    return jsonify({"error": "Inventory service unavailable", "error_code": 9003}), 503


@infrastructure_bp.route('/api/fulfillment/dispatch', methods=['POST'])
def dispatch_fulfillment():
    error("Received malformed response from downstream fulfillment provider",
          {"error_code": 9004, "provider": "FulfillmentCo", "upstream_status": 502})
    return jsonify({"error": "Bad gateway — fulfillment service error", "error_code": 9004}), 502
