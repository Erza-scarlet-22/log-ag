# Simulated order management API routes.
#
# These endpoints always return error responses to produce representative log
# events for dashboard testing and demonstration purposes.
#
# Routes:
#   POST   /api/orders            — Insufficient stock (409).
#   GET    /api/orders/<order_id> — Order not found (404).
#   DELETE /api/orders/<order_id> — Order already dispatched (409).

from flask import Blueprint, jsonify
try:
    from ..logger import error  # type: ignore[reportMissingImports]
except ImportError:
    from logger import error  # type: ignore[reportMissingImports]

orders_bp = Blueprint('orders', __name__)


@orders_bp.route('/api/orders', methods=['POST'])
def create_order():
    error("Requested quantity exceeds available stock level",
          {"error_code": 7001, "product_id": "SKU-9921", "requested": 50, "available": 3})
    return jsonify({"error": "Stock depleted", "error_code": 7001}), 409


@orders_bp.route('/api/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    error("Order not found or belongs to a different account",
          {"error_code": 7002, "order_id": order_id})
    return jsonify({"error": "Order not found", "error_code": 7002}), 404


@orders_bp.route('/api/orders/<order_id>', methods=['DELETE'])
def cancel_order(order_id):
    error("Cannot cancel order — shipment already dispatched",
          {"error_code": 7003, "order_id": order_id, "status": "dispatched"})
    return jsonify({"error": "Order already shipped", "error_code": 7003}), 409
