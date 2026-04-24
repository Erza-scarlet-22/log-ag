# lambda/servicenow_lambda_handler.py
#
# Bedrock action group handler for ALL ServiceNow operations.
#
# Functions exposed to the Bedrock agent:
#   createIncident  — creates a new incident, returns ticket number + URL
#   getTicketStatus — fetches current state of an existing ticket
#   updateTicket    — adds a work note or resolves a ticket after remediation
#
# Environment variables:
#   SERVICENOW_SECRET_NAME  — Secrets Manager key (default: servicenow/credentials)
#   AWS_DEFAULT_REGION
#
# Secrets Manager secret structure:
#   {
#     "instance_url": "https://dev12345.service-now.com",
#     "username":     "aws-integration-user",
#     "password":     "yourpassword"
#   }
#
# If ServiceNow credentials are missing or invalid the handler returns a
# demo_mode response with a fake INC number so the rest of the Bedrock
# flow (SSL Lambda, etc.) continues uninterrupted.

import base64
import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

# ── Error classification maps ──────────────────────────────────────────────────

URGENCY_MAP = {
    "ssl_expired":      "1",   # Critical
    "db_storage":       "1",   # Critical
    "compute_overload": "2",   # High
    "db_connection":    "2",   # High
    "password_expired": "2",   # High
    "ssl_expiring":     "3",   # Medium
}

CATEGORY_MAP = {
    "ssl_expired":      "Security",
    "ssl_expiring":     "Security",
    "password_expired": "Security",
    "db_storage":       "Database",
    "db_connection":    "Database",
    "compute_overload": "Infrastructure",
}

PRIORITY_LABEL = {"1": "1 - Critical", "2": "2 - High", "3": "3 - Medium", "4": "4 - Low"}

STATE_LABEL = {
    "1": "New", "2": "In Progress", "3": "On Hold",
    "6": "Resolved", "7": "Closed", "8": "Canceled",
}


# ── Credentials ───────────────────────────────────────────────────────────────

def _get_creds() -> dict:
    """Fetch ServiceNow credentials from Secrets Manager."""
    secret_name = os.getenv("SERVICENOW_SECRET_NAME", "servicenow/credential")
    resp = _sm.get_secret_value(SecretId=secret_name)
    return json.loads(resp["SecretString"])


def _auth_header(creds: dict) -> str:
    """Build Basic Auth header value from credentials dict."""
    return "Basic " + base64.b64encode(
        f"{creds['username']}:{creds['password']}".encode()
    ).decode()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _snow_get(creds: dict, path: str) -> dict:
    """GET request to ServiceNow REST API."""
    url = f"{creds['instance_url'].rstrip('/')}{path}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": _auth_header(creds)},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _snow_post(creds: dict, path: str, body: dict) -> dict:
    """POST request to ServiceNow REST API."""
    url  = f"{creds['instance_url'].rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Authorization": _auth_header(creds),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _snow_patch(creds: dict, path: str, body: dict) -> dict:
    """PATCH request to ServiceNow REST API (update a record)."""
    url  = f"{creds['instance_url'].rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type":  "application/json",
            "Accept":        "application/json",
            "Authorization": _auth_header(creds),
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ── ServiceNow operations ──────────────────────────────────────────────────────

def _create_incident(creds: dict, params: dict) -> dict:
    """
    Create a new ServiceNow incident.

    Returns:
      ticket_number, ticket_sys_id, ticket_url, status, urgency, priority
    """
    error_type  = params.get("error_type", "unknown")
    description = params.get("error_description", "Error detected by Log Aggregator")
    status_code = params.get("status_code", "")
    count       = params.get("count", "1")
    last_seen   = params.get("last_seen", datetime.now(timezone.utc).isoformat())
    urgency     = URGENCY_MAP.get(error_type, "2")

    body = {
        "short_description": f"[AWS Log Aggregator] {description}",
        "description": (
            f"Incident automatically detected by AWS Log Aggregator.\n\n"
            f"Error Type:       {error_type}\n"
            f"HTTP Status Code: {status_code}\n"
            f"Occurrences:      {count}\n"
            f"Last Seen:        {last_seen}\n\n"
            f"Source: AWS Log Aggregator Auto-Remediation\n"
            f"Bedrock Agent: ssl_remediation_action_group"
        ),
        "urgency":                 urgency,
        "impact":                  urgency,
        "category":                CATEGORY_MAP.get(error_type, "Infrastructure"),
        "subcategory":             error_type,
        "assignment_group":        "AWS Operations",
        "u_source":                "AWS Log Aggregator",
        "u_aws_error_code":        str(status_code),
        "u_aws_error_type":        error_type,
        "u_remediation_status":    "pending",
        "work_notes":              f"Auto-created by Bedrock agent. Remediation in progress.",
    }

    result = _snow_post(creds, "/api/now/table/incident", body)
    row    = result.get("result", {})

    ticket_number = row.get("number", "UNKNOWN")
    ticket_sys_id = row.get("sys_id", "")
    ticket_url    = (
        f"{creds['instance_url'].rstrip('/')}"
        f"/nav_to.do?uri=incident.do?sys_id={ticket_sys_id}"
    )

    logger.info("Incident created: %s  sys_id=%s", ticket_number, ticket_sys_id)

    return {
        "ticket_number":  ticket_number,
        "ticket_sys_id":  ticket_sys_id,
        "ticket_url":     ticket_url,
        "urgency":        PRIORITY_LABEL.get(urgency, urgency),
        "category":       CATEGORY_MAP.get(error_type, "Infrastructure"),
        "status":         "created",
        "error_type":     error_type,
    }


def _get_ticket_status(creds: dict, params: dict) -> dict:
    """
    Fetch the current state of an existing ServiceNow ticket.
    Used by the dashboard to poll ticket status after creation.
    """
    ticket_number = params.get("ticket_number", "")
    if not ticket_number:
        raise ValueError("ticket_number parameter is required")

    fields = "number,state,priority,urgency,short_description,description,assigned_to,sys_updated_on,close_notes,work_notes"
    path   = f"/api/now/table/incident?sysparm_query=number={ticket_number}&sysparm_fields={fields}"

    result = _snow_get(creds, path)
    rows   = result.get("result", [])

    if not rows:
        return {"error": f"Ticket {ticket_number} not found", "ticket_number": ticket_number}

    row       = rows[0]
    state_raw = _display_val(row.get("state", "1"))

    return {
        "ticket_number":     ticket_number,
        "state":             state_raw,
        "state_label":       STATE_LABEL.get(state_raw, "Unknown"),
        "priority":          _display_val(row.get("priority", "")),
        "short_description": _display_val(row.get("short_description", "")),
        "assigned_to":       _display_val(row.get("assigned_to", "")),
        "updated_at":        _display_val(row.get("sys_updated_on", "")),
        "close_notes":       _display_val(row.get("close_notes", "")),
        "ticket_url": (
            f"{creds['instance_url'].rstrip('/')}"
            f"/nav_to.do?uri=incident.do?sysparm_query=number={ticket_number}"
        ),
        "status": "found",
    }


def _update_ticket(creds: dict, params: dict) -> dict:
    """
    Add a work note to an existing ticket or mark it resolved.
    Called by the Bedrock agent after the SSL (or other) Lambda completes remediation.

    params:
      ticket_number   — INC0001234
      work_note       — text to append to work notes
      resolve         — "true" to close the ticket
      resolution_note — close notes when resolving
    """
    ticket_number   = params.get("ticket_number", "")
    work_note       = params.get("work_note", "")
    resolve         = str(params.get("resolve", "false")).lower() == "true"
    resolution_note = params.get("resolution_note", "Issue resolved by AWS auto-remediation.")

    if not ticket_number:
        raise ValueError("ticket_number parameter is required")

    # First get the sys_id
    path   = f"/api/now/table/incident?sysparm_query=number={ticket_number}&sysparm_fields=sys_id,state"
    result = _snow_get(creds, path)
    rows   = result.get("result", [])

    if not rows:
        return {"error": f"Ticket {ticket_number} not found", "ticket_number": ticket_number}

    sys_id = rows[0].get("sys_id", {})
    if isinstance(sys_id, dict):
        sys_id = sys_id.get("value", "")

    patch_body: dict = {}

    if work_note:
        patch_body["work_notes"] = work_note

    if resolve:
        patch_body["state"]              = "6"   # Resolved
        patch_body["close_code"]         = "Solved (Permanently)"
        patch_body["close_notes"]        = resolution_note
        patch_body["u_remediation_status"] = "completed"

    if patch_body:
        _snow_patch(creds, f"/api/now/table/incident/{sys_id}", patch_body)

    logger.info("Ticket %s updated. resolve=%s", ticket_number, resolve)

    return {
        "ticket_number": ticket_number,
        "updated":       True,
        "resolved":      resolve,
        "work_note":     work_note,
        "status":        "updated",
    }


# ── Demo mode fallback ────────────────────────────────────────────────────────

def _demo_response(function_name: str, params: dict, error: str) -> dict:
    """
    Return a plausible demo response when ServiceNow is not configured.
    The Bedrock orchestration flow continues — only the real ticket is missing.
    """
    error_type = params.get("error_type", "unknown")
    ticket_num = "INC_DEMO_001"

    if function_name == "createIncident":
        return {
            "ticket_number": ticket_num,
            "ticket_url":    "https://demo.service-now.com/incident/INC_DEMO_001",
            "urgency":       PRIORITY_LABEL.get(URGENCY_MAP.get(error_type, "2"), "2 - High"),
            "category":      CATEGORY_MAP.get(error_type, "Infrastructure"),
            "status":        "demo_mode",
            "error_type":    error_type,
            "demo_note":     "ServiceNow not configured. Set servicenow/credential in Secrets Manager.",
            "error":         error,
        }
    elif function_name == "getTicketStatus":
        return {
            "ticket_number": params.get("ticket_number", ticket_num),
            "state":         "2",
            "state_label":   "In Progress",
            "priority":      "2 - High",
            "short_description": "Auto-detected error — demo mode",
            "assigned_to":   "AWS Operations",
            "demo_mode":     True,
            "note":          "ServiceNow not configured.",
        }
    else:  # updateTicket
        return {
            "ticket_number": params.get("ticket_number", ticket_num),
            "updated":       True,
            "demo_mode":     True,
            "note":          "ServiceNow not configured.",
        }


# ── Lambda handler ────────────────────────────────────────────────────────────

def handler(event, context):
    """
    Bedrock action group handler for all ServiceNow operations.

    Bedrock sends:
    {
      "actionGroup": "servicenow_action_group",
      "function":    "createIncident" | "getTicketStatus" | "updateTicket",
      "parameters":  [ {"name": "...", "value": "..."}, ... ]
    }
    """
    logger.info("ServiceNow Lambda invoked: %s", json.dumps(event))

    function_name = event.get("function", "createIncident")
    params        = {p["name"]: p["value"] for p in event.get("parameters", [])}

    logger.info("Function: %s  Params: %s", function_name, params)

    try:
        creds = _get_creds()

        if function_name == "createIncident":
            response_body = _create_incident(creds, params)

        elif function_name == "getTicketStatus":
            response_body = _get_ticket_status(creds, params)

        elif function_name == "updateTicket":
            response_body = _update_ticket(creds, params)

        else:
            response_body = {"error": f"Unknown function: {function_name}", "status": "error"}

    except Exception as exc:
        logger.error("ServiceNow operation failed (%s): %s", function_name, exc)
        response_body = _demo_response(function_name, params, str(exc))

    return {
        "actionGroup":  event.get("actionGroup", "servicenow_action_group"),
        "function":     function_name,
        "functionResponse": {
            "responseBody": {
                "TEXT": {"body": json.dumps(response_body)}
            }
        },
    }


# ── Helper ────────────────────────────────────────────────────────────────────

def _display_val(field) -> str:
    """ServiceNow fields can be either a plain string or {"display_value": ..., "value": ...}."""
    if isinstance(field, dict):
        return field.get("display_value") or field.get("value") or ""
    return str(field) if field else ""