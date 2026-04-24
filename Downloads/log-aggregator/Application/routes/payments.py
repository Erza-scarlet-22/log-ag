# Simulated payment API routes.
#
# These endpoints always return error responses to produce representative log
# events for dashboard testing and demonstration purposes.
#
# Routes:
#   POST /api/payments/charge  — Simulates a card decline (402) or gateway timeout (503).
#   POST /api/payments/refund  — Simulates a refund window expiry (422).

from flask import Blueprint, jsonify, request
try:
    from ..logger import error  # type: ignore[reportMissingImports]
except ImportError:
    from logger import error  # type: ignore[reportMissingImports]

payments_bp = Blueprint('payments', __name__)


@payments_bp.route('/api/payments/charge', methods=['POST'])
def payment_charge():
    data = request.get_json() or {}

    # Allow callers to trigger the gateway-timeout scenario via a simulate flag.
    if data.get('simulate') == 'gateway_timeout':
        error("Payment gateway did not respond within SLA threshold",
              {"error_code": 5001, "gateway": "Stripe", "timeout_ms": 5000})
        return jsonify({"error": "Payment gateway timeout", "error_code": 5001}), 503

    # Default scenario: card declined due to insufficient funds.
    error("Card declined by issuer — insufficient funds",
          {"error_code": 5002, "gateway": "Stripe", "card_last4": "4242"})
    return jsonify({"error": "Card declined", "error_code": 5002}), 402


@payments_bp.route('/api/payments/refund', methods=['POST'])
def payment_refund():
    error("Refund window expired — transaction is older than 90 days",
          {"error_code": 5003, "transaction_age_days": 92})
    return jsonify({"error": "Refund window expired", "error_code": 5003}), 422
