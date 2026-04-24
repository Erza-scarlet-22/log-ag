# Dashboard/dashboard_blueprint.py
#
# Routes:
#   GET  /dashboard                  — Serves the dashboard HTML
#   GET  /api/dashboard-data         — JSON payload for charts
#   GET  /api/dashboard-report.pdf   — PDF report download
#   POST /api/chat-insights          — Chat question → Bedrock agent
#   POST /api/create-snow-ticket     — NEW: Step 1 — create ServiceNow ticket only
#   POST /api/fix-error              — Step 2 — trigger full remediation after ticket exists
#   GET  /api/snow-ticket/<ticket>   — NEW: Poll ServiceNow ticket status

from datetime import date
from flask import Blueprint, jsonify, render_template, request, send_file

try:
    from .bedrock_chat_service import generate_error_insight   # type: ignore
    BEDROCK_CHAT_AVAILABLE = True
except Exception:
    BEDROCK_CHAT_AVAILABLE = False

try:
    from .dashboard_pdf_service import build_dashboard_pdf, REPORTLAB_AVAILABLE  # type: ignore
except Exception:
    REPORTLAB_AVAILABLE = False
    def build_dashboard_pdf(_): ...

from .dashboard_data_service import build_dashboard_payload   # type: ignore


def create_dashboard_blueprint(conversion_dir: str, run_conversion_outputs):

    dashboard_bp = Blueprint('dashboard', __name__, template_folder='templates')

    # ── Existing routes ───────────────────────────────────────────────────────

    @dashboard_bp.route('/dashboard', methods=['GET'])
    def dashboard_page():
        return render_template('dashboard.html')

    @dashboard_bp.route('/api/dashboard-data', methods=['GET'])
    def dashboard_data():
        payload = build_dashboard_payload(conversion_dir, run_conversion_outputs, request.args)
        return jsonify(payload), 200

    @dashboard_bp.route('/api/dashboard-report.pdf', methods=['GET'])
    def dashboard_report_pdf():
        if not REPORTLAB_AVAILABLE:
            return jsonify({'error': 'PDF export unavailable — install reportlab.'}), 503
        payload    = build_dashboard_payload(conversion_dir, run_conversion_outputs, request.args)
        pdf_buffer = build_dashboard_pdf(payload)
        filename   = f"error-dashboard-report-{date.today().isoformat()}.pdf"
        return send_file(pdf_buffer, mimetype='application/pdf',
                         as_attachment=True, download_name=filename)

    @dashboard_bp.route('/api/chat-insights', methods=['POST'])
    def chat_insights():
        """Forward a user question to the Bedrock orchestrator agent (analysis mode)."""
        payload       = request.get_json(silent=True) or {}
        error_context = payload.get('error') or {}
        user_message  = (payload.get('message') or '').strip()
        history       = payload.get('history') or []
        session_id    = (payload.get('sessionId') or '').strip()

        if not isinstance(error_context, dict):
            return jsonify({'error': 'Invalid payload: error context must be an object'}), 400
        if not isinstance(history, list):
            return jsonify({'error': 'Invalid payload: history must be a list'}), 400
        if not user_message:
            user_message = 'Provide root cause analysis and remediation steps for this error.'

        if not BEDROCK_CHAT_AVAILABLE:
            return jsonify({'error': 'Bedrock chat service unavailable.'}), 503

        try:
            reply_text, metadata = generate_error_insight(
                error_context, user_message, history, session_id
            )
            return jsonify({
                'reply':     reply_text,
                'provider':  'aws-bedrock-agent',
                'sessionId': metadata.get('session_id', session_id),
            }), 200
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    # ── NEW: Step 1 — Create ServiceNow ticket ────────────────────────────────

    @dashboard_bp.route('/api/create-snow-ticket', methods=['POST'])
    def create_snow_ticket():
        """
        Step 1 of the remediation flow.

        Called when the engineer clicks "Create ServiceNow Ticket" in the dashboard.
        Invokes the Bedrock agent with an explicit instruction to ONLY create a
        ServiceNow incident and return the ticket number — no remediation yet.

        Request body:
        {
          "error": { ...error row from dashboard table... }
        }

        Response:
        {
          "ticket_number": "INC0001234",
          "ticket_url":    "https://...",
          "session_id":    "...",
          "reply":         "Full agent text response",
          "error_type":    "ssl_expired"
        }
        """
        if not BEDROCK_CHAT_AVAILABLE:
            return jsonify({'error': 'Bedrock agent unavailable.'}), 503

        payload       = request.get_json(silent=True) or {}
        error_context = payload.get('error') or {}

        if not error_context:
            return jsonify({'error': 'No error context provided'}), 400

        error_type  = _classify_error_type(error_context)
        description = error_context.get('Description', 'Unknown error')
        status_code = error_context.get('Status Code', '')
        count       = error_context.get('Count', 1)
        last_seen   = error_context.get('Last Seen', '')

        # Tell the agent to ONLY create the ServiceNow ticket, nothing else
        ticket_message = (
            f"Create a ServiceNow incident for this error. Do NOT perform any remediation yet. "
            f"Error type: {error_type}. "
            f"Description: {description}. "
            f"Status code: {status_code}. "
            f"Occurrence count: {count}. "
            f"Last seen: {last_seen}. "
            f"Call servicenow_action_group → createIncident only. "
            f"Return the ticket number and URL. Stop after the ticket is created."
        )

        try:
            reply_text, metadata = generate_error_insight(
                error_context,
                ticket_message,
                [],
                None,
            )

            # Extract ticket number from agent reply for convenience
            ticket_number = _extract_ticket_number(reply_text)
            ticket_url    = _extract_ticket_url(reply_text)

            return jsonify({
                'reply':         reply_text,
                'ticket_number': ticket_number,
                'ticket_url':    ticket_url,
                'session_id':    metadata.get('session_id', ''),
                'error_type':    error_type,
                'status':        'ticket_created',
            }), 200

        except Exception as exc:
            return jsonify({'error': str(exc), 'status': 'failed'}), 500

    # ── NEW: Step 2 — Run remediation after ticket exists ─────────────────────

    @dashboard_bp.route('/api/fix-error', methods=['POST'])
    def fix_error():
        """
        Step 2 of the remediation flow.

        Called AFTER a ServiceNow ticket has been created (Step 1).
        The agent already knows the ticket number from the session.
        This call tells the agent to now perform the actual remediation.

        Request body:
        {
          "error":          { ...error row... },
          "session_id":     "abc123",        ← session from Step 1 (keeps ticket context)
          "ticket_number":  "INC0001234",    ← for logging / display
          "history":        [...]            ← prior chat turns including ticket creation
        }

        Response:
        {
          "reply":      "Agent remediation response",
          "session_id": "...",
          "error_type": "ssl_expired",
          "status":     "remediation_initiated"
        }
        """
        if not BEDROCK_CHAT_AVAILABLE:
            return jsonify({'error': 'Bedrock agent unavailable.'}), 503

        payload        = request.get_json(silent=True) or {}
        error_context  = payload.get('error') or {}
        session_id     = (payload.get('session_id') or '').strip()
        ticket_number  = (payload.get('ticket_number') or '').strip()
        history        = payload.get('history') or []

        if not error_context:
            return jsonify({'error': 'No error context provided'}), 400

        error_type  = _classify_error_type(error_context)
        description = error_context.get('Description', 'Unknown error')
        status_code = error_context.get('Status Code', '')

        # Build the remediation instruction — references the ticket already created
        ticket_ref = f"(ticket {ticket_number})" if ticket_number else ""
        fix_message = (
            f"The ServiceNow incident has been created {ticket_ref}. "
            f"Now perform the remediation. "
            f"Error type: {error_type}. "
            f"Description: {description}. "
            f"Status code: {status_code}. "
            f"Call the appropriate remediation action group for this error type. "
            f"Report what action was taken and the expected resolution time."
        )

        try:
            reply_text, metadata = generate_error_insight(
                error_context,
                fix_message,
                history,
                session_id or None,
            )

            return jsonify({
                'reply':      reply_text,
                'session_id': metadata.get('session_id', session_id),
                'error_type': error_type,
                'status':     'remediation_initiated',
            }), 200

        except Exception as exc:
            return jsonify({'error': str(exc), 'status': 'failed'}), 500

    # ── NEW: Poll ServiceNow ticket status ────────────────────────────────────

    @dashboard_bp.route('/api/snow-ticket/<ticket_number>', methods=['GET'])
    def get_snow_ticket(ticket_number: str):
        """
        Poll the ServiceNow ticket status.
        The dashboard calls this after Step 1 to show live ticket status.

        Reads ServiceNow credentials from Secrets Manager (same secret the Lambda uses).
        Returns a simplified status object for display in the dashboard.
        """
        import os, json, base64, urllib.request
        import boto3

        secret_name = os.getenv('SERVICENOW_SECRET_NAME', 'servicenow/credential')
        region      = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

        try:
            sm     = boto3.client('secretsmanager', region_name=region)
            creds  = json.loads(sm.get_secret_value(SecretId=secret_name)['SecretString'])
        except Exception as exc:
            # ServiceNow not configured — return a demo status
            return jsonify({
                'ticket_number': ticket_number,
                'state':         'New',
                'state_label':   'New',
                'priority':      '2 - High',
                'short_description': 'Auto-detected error — see dashboard',
                'assigned_to':   'AWS Operations',
                'demo_mode':     True,
                'note':          'Configure servicenow/credential in Secrets Manager for live status.',
            }), 200

        try:
            base_url = creds['instance_url'].rstrip('/')
            url      = f"{base_url}/api/now/table/incident?sysparm_query=number={ticket_number}&sysparm_fields=number,state,priority,short_description,assigned_to,sys_updated_on,close_notes"
            token    = base64.b64encode(f"{creds['username']}:{creds['password']}".encode()).decode()

            req = urllib.request.Request(
                url,
                headers={'Accept': 'application/json', 'Authorization': f'Basic {token}'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data   = json.loads(resp.read().decode())
                result = (data.get('result') or [{}])[0]

            state_labels = {
                '1': 'New', '2': 'In Progress', '3': 'On Hold',
                '6': 'Resolved', '7': 'Closed', '8': 'Canceled',
            }
            state_raw = str(result.get('state', '1'))

            return jsonify({
                'ticket_number':     ticket_number,
                'state':             state_raw,
                'state_label':       state_labels.get(state_raw, 'Unknown'),
                'priority':          result.get('priority', {}).get('display_value', ''),
                'short_description': result.get('short_description', {}).get('display_value', ''),
                'assigned_to':       result.get('assigned_to', {}).get('display_value', ''),
                'updated_at':        result.get('sys_updated_on', {}).get('display_value', ''),
                'close_notes':       result.get('close_notes', {}).get('display_value', ''),
                'ticket_url':        f"{base_url}/nav_to.do?uri=incident.do?sysparm_query=number={ticket_number}",
                'demo_mode':         False,
            }), 200

        except Exception as exc:
            return jsonify({'error': str(exc), 'ticket_number': ticket_number}), 500

    return dashboard_bp


# ── Helpers ───────────────────────────────────────────────────────────────────

def _classify_error_type(error_context: dict) -> str:
    """Map error context dict to a known error_type string."""
    status_code = str(error_context.get('Status Code', ''))
    error_code  = str(error_context.get('Error Code', ''))
    description = (error_context.get('Description') or '').lower()

    code_map = {
        '9010': 'ssl_expired',    '9011': 'ssl_expiring',
        '9012': 'password_expired', '9013': 'db_storage',
        '9014': 'db_connection',  '9015': 'compute_overload',
    }
    if error_code in code_map:
        return code_map[error_code]

    status_map = {
        '495': 'ssl_expired', '507': 'db_storage',
        '504': 'db_connection', '503': 'compute_overload', '401': 'password_expired',
    }
    if status_code in status_map:
        return status_map[status_code]

    if 'ssl' in description or 'cert' in description:
        return 'ssl_expired'
    if 'password' in description or 'auth' in description:
        return 'password_expired'
    if 'storage' in description or 'capacity' in description:
        return 'db_storage'
    if 'connection' in description or 'pool' in description:
        return 'db_connection'
    if 'cpu' in description or 'memory' in description or 'compute' in description:
        return 'compute_overload'
    return 'unknown'


def _extract_ticket_number(text: str) -> str:
    """Pull INC/CHG/RITM number from agent response text."""
    import re
    match = re.search(r'\b(INC|CHG|RITM|INC_DEMO)[_\-]?\d+', text, re.IGNORECASE)
    return match.group(0).upper() if match else ''


def _extract_ticket_url(text: str) -> str:
    """Pull the first https URL from agent response text."""
    import re
    match = re.search(r'https?://[^\s\)]+', text)
    return match.group(0) if match else ''