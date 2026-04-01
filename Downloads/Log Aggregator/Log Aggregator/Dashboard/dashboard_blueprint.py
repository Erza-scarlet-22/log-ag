# Dashboard Flask blueprint for the Log Aggregator.
#
# Registers four routes under the 'dashboard' blueprint:
#   GET  /dashboard                — Serves the single-page dashboard HTML.
#   GET  /api/dashboard-data       — Returns the JSON payload for the front-end charts.
#   GET  /api/dashboard-report.pdf — Downloads a landscape PDF summary report.
#   POST /api/chat-insights        — Proxies a question to the AWS Bedrock agent.
#
# Data aggregation logic  → dashboard_data_service.py
# PDF rendering logic     → dashboard_pdf_service.py
# AWS Bedrock integration → bedrock_chat_service.py

from datetime import date
from flask import Blueprint, jsonify, render_template, request, send_file

try:
    from bedrock_chat_service import generate_error_insight  # type: ignore[reportMissingImports]  # noqa: F401 — imported for side-effect availability check
    BEDROCK_CHAT_AVAILABLE = True
except Exception:
    BEDROCK_CHAT_AVAILABLE = False

try:
    from dashboard_pdf_service import build_dashboard_pdf, REPORTLAB_AVAILABLE  # type: ignore[reportMissingImports]
except Exception:
    REPORTLAB_AVAILABLE = False
    def build_dashboard_pdf(_): ...  # Stub — never called when REPORTLAB_AVAILABLE is False.

# Dashboard data assembly lives in a dedicated service module to keep this file thin.
from dashboard_data_service import build_dashboard_payload  # type: ignore[reportMissingImports]


# ── Blueprint factory ─────────────────────────────────────────────────────────

def create_dashboard_blueprint(conversion_dir: str, run_conversion_outputs):
    """Create and return the dashboard Blueprint.

    Args:
        conversion_dir: Absolute path to the Conversion directory containing the
                        CSV and JSON artefacts read by the data service.
        run_conversion_outputs: Callback that regenerates those artefacts from
                                the latest application log before each data read.
    """
    dashboard_bp = Blueprint('dashboard', __name__, template_folder='templates')

    # ── Route handlers ────────────────────────────────────────────────────────

    @dashboard_bp.route('/dashboard', methods=['GET'])
    def dashboard_page():
        # Serve the static single-page app shell; all data is loaded via AJAX.
        return render_template('dashboard.html')

    @dashboard_bp.route('/api/dashboard-data', methods=['GET'])
    def dashboard_data():
        # Assemble and return the full dashboard payload, applying any date filter
        # present in the query string (preset, from, to).
        payload = build_dashboard_payload(conversion_dir, run_conversion_outputs, request.args)
        return jsonify(payload), 200

    @dashboard_bp.route('/api/dashboard-report.pdf', methods=['GET'])
    def dashboard_report_pdf():
        if not REPORTLAB_AVAILABLE:
            return jsonify({'error': 'PDF export is unavailable. Install reportlab and restart the app.'}), 503
        payload    = build_dashboard_payload(conversion_dir, run_conversion_outputs, request.args)
        pdf_buffer = build_dashboard_pdf(payload)
        filename   = f"error-dashboard-report-{date.today().isoformat()}.pdf"
        return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True, download_name=filename)

    @dashboard_bp.route('/api/chat-insights', methods=['POST'])
    def chat_insights():
        """Forward a user question and selected error context to the AWS Bedrock agent."""
        payload       = request.get_json(silent=True) or {}
        error_context = payload.get('error') or {}
        user_message  = (payload.get('message') or '').strip()
        history       = payload.get('history') or []
        session_id    = (payload.get('sessionId') or '').strip()

        # Validate payload shape before forwarding to the external service.
        if not isinstance(error_context, dict):
            return jsonify({'error': 'Invalid payload: error context must be an object'}), 400
        if not isinstance(history, list):
            return jsonify({'error': 'Invalid payload: history must be a list'}), 400

        if not user_message:
            user_message = 'Provide insights and remediation steps for this selected error.'

        if not BEDROCK_CHAT_AVAILABLE:
            return jsonify({
                'error': 'AWS Bedrock chat service is not available. Ensure boto3 is installed and AWS credentials are configured.'
            }), 503

        try:
            reply_text, metadata = generate_error_insight(error_context, user_message, history, session_id)
            return jsonify({
                'reply':     reply_text,
                'provider':  'aws-bedrock-agent',
                'modelId':   metadata.get('model_id', ''),
                'region':    metadata.get('region', ''),
                'sessionId': metadata.get('session_id', session_id),
            }), 200
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    return dashboard_bp
