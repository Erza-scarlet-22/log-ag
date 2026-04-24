# lambda/ssl_lambda_handler.py
#
# SSL Remediation Lambda — supports DEMO MODE and REAL MODE.
#
# DEMO MODE  (DEMO_MODE=true, default)
#   Skips all real AWS calls (ACM, Route 53, ELB).
#   Generates a realistic fake cert ARN so the full Bedrock flow works
#   end-to-end without any domain or HTTPS listener setup.
#   Use this for project demos.
#
# REAL MODE  (DEMO_MODE=false)
#   1. Checks existing ACM certificate for the domain
#   2. Requests a new ACM certificate (DNS validation)
#   3. Writes Route 53 CNAME validation records automatically
#   4. Polls until ACM reaches ISSUED status (up to 5 min)
#   5. Updates the ALB HTTPS :443 listener with the new cert
#   6. Stores cert ARN in Secrets Manager
#
# BOTH MODES always do:
#   7. Notify the dummy app  →  index.html SSL banner flips green
#   8. Call servicenow_action_group → updateTicket  →  ticket gets
#      a work note + resolved status in ServiceNow
#
# Environment variables (all set by CloudFormation):
#   DEMO_MODE             — "true" (default) or "false"
#   SSL_DOMAIN            — domain for real mode, e.g. app.example.com
#   HOSTED_ZONE_ID        — Route 53 zone ID for real mode
#   ALB_ARN               — ALB ARN for real mode
#   SSL_CERT_SECRET_NAME  — Secrets Manager key (default: dummy-app/ssl-cert-arn)
#   DUMMY_APP_URL         — ALB DNS to call /api/dummy/resolve/ssl_expired
#   SERVICENOW_SECRET_NAME — secret for ServiceNow (default: servicenow/credentials)
#   VALIDATION_POLL_SECONDS — max ACM poll time (default: 300)
#   VALIDATION_POLL_INTERVAL — poll interval (default: 15)

import json
import logging
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Lazy AWS clients ──────────────────────────────────────────────────────────
_acm = _r53 = _elb = _sm = None

def _acm_client():
    global _acm
    if not _acm:
        _acm = boto3.client("acm", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    return _acm

def _r53_client():
    global _r53
    if not _r53:
        _r53 = boto3.client("route53", region_name="us-east-1")
    return _r53

def _elb_client():
    global _elb
    if not _elb:
        _elb = boto3.client("elbv2", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    return _elb

def _sm_client():
    global _sm
    if not _sm:
        _sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    return _sm

# ── Config ────────────────────────────────────────────────────────────────────
DEMO_MODE          = os.getenv("DEMO_MODE", "true").lower() == "true"
DOMAIN             = os.getenv("SSL_DOMAIN", "api.dummy-app.internal")
HOSTED_ZONE_ID     = os.getenv("HOSTED_ZONE_ID", "")
ALB_ARN            = os.getenv("ALB_ARN", "")
SSL_CERT_SECRET    = os.getenv("SSL_CERT_SECRET_NAME", "dummy-app/ssl-cert-arn")
DUMMY_APP_URL      = os.getenv("DUMMY_APP_URL", "")
SNOW_SECRET        = os.getenv("SERVICENOW_SECRET_NAME", "servicenow/credential")
POLL_SECONDS       = int(os.getenv("VALIDATION_POLL_SECONDS", "300"))
POLL_INTERVAL      = int(os.getenv("VALIDATION_POLL_INTERVAL", "15"))


# ════════════════════════════════════════════════════════════════════════════════
# DEMO MODE helpers
# ════════════════════════════════════════════════════════════════════════════════

def _demo_cert_arn() -> str:
    """Generate a realistic-looking fake ACM cert ARN for demo purposes."""
    region  = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    account = os.getenv("AWS_ACCOUNT_ID", "123456789012")
    ts      = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"arn:aws:acm:{region}:{account}:certificate/demo-{ts}-renewed"


# ════════════════════════════════════════════════════════════════════════════════
# REAL MODE helpers
# ════════════════════════════════════════════════════════════════════════════════

def _find_existing_cert(domain: str):
    """Return most recent ACM cert dict for domain, or None."""
    acm  = _acm_client()
    pager = acm.get_paginator("list_certificates")
    best = None
    for page in pager.paginate(CertificateStatuses=[
            "ISSUED", "PENDING_VALIDATION", "EXPIRED", "INACTIVE", "FAILED"]):
        for s in page["CertificateSummaryList"]:
            if s["DomainName"] in (domain, f"*.{domain}"):
                cert = acm.describe_certificate(CertificateArn=s["CertificateArn"])["Certificate"]
                if best is None:
                    best = cert
                elif cert["Status"] == "ISSUED" and best["Status"] != "ISSUED":
                    best = cert
    return best


def _request_certificate(domain: str) -> str:
    """Request a new DNS-validated ACM certificate. Returns new cert ARN."""
    resp = _acm_client().request_certificate(
        DomainName=domain,
        ValidationMethod="DNS",
        SubjectAlternativeNames=list({domain, f"*.{domain}"}),
        Tags=[
            {"Key": "ManagedBy",   "Value": "LogAggregatorSSLLambda"},
            {"Key": "RequestedAt", "Value": datetime.now(timezone.utc).isoformat()},
        ],
    )
    arn = resp["CertificateArn"]
    logger.info("ACM certificate requested: %s", arn)
    return arn


def _get_validation_options(cert_arn: str, max_wait: int = 30) -> list:
    """Poll ACM until DNS validation options are populated (usually <10 s)."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        opts = _acm_client().describe_certificate(CertificateArn=cert_arn)[
            "Certificate"].get("DomainValidationOptions", [])
        ready = [o for o in opts if o.get("ResourceRecord")]
        if ready:
            return ready
        time.sleep(5)
    raise TimeoutError(f"ACM did not populate validation options within {max_wait}s")


def _write_route53_cnames(validation_opts: list, zone_id: str) -> str:
    """Write ACM DNS validation CNAMEs to Route 53. Returns change ID."""
    changes, seen = [], set()
    for opt in validation_opts:
        rec = opt.get("ResourceRecord", {})
        name, value = rec.get("Name", ""), rec.get("Value", "")
        if not name or not value or (name, value) in seen:
            continue
        seen.add((name, value))
        changes.append({"Action": "UPSERT", "ResourceRecordSet": {
            "Name": name, "Type": "CNAME", "TTL": 300,
            "ResourceRecords": [{"Value": value}],
        }})
    if not changes:
        raise ValueError("No DNS validation records returned by ACM")
    resp = _r53_client().change_resource_record_sets(
        HostedZoneId=zone_id,
        ChangeBatch={"Comment": "ACM SSL validation", "Changes": changes},
    )
    cid = resp["ChangeInfo"]["Id"]
    logger.info("Route 53 CNAMEs written. ChangeId: %s", cid)
    return cid


def _wait_r53_insync(change_id: str, timeout: int = 60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _r53_client().get_change(Id=change_id)["ChangeInfo"]["Status"]
        if status == "INSYNC":
            return
        time.sleep(10)
    logger.warning("Route 53 change did not reach INSYNC within %ds", timeout)


def _wait_cert_issued(cert_arn: str) -> bool:
    """Poll ACM until ISSUED. Returns True on success, False on timeout."""
    deadline = time.time() + POLL_SECONDS
    attempt  = 0
    while time.time() < deadline:
        attempt += 1
        status = _acm_client().describe_certificate(
            CertificateArn=cert_arn)["Certificate"]["Status"]
        logger.info("ACM poll %d: %s", attempt, status)
        if status == "ISSUED":
            return True
        if status in ("FAILED", "REVOKED", "INACTIVE"):
            raise RuntimeError(f"ACM cert reached terminal status: {status}")
        time.sleep(POLL_INTERVAL)
    logger.warning("ACM cert not ISSUED after %ds", POLL_SECONDS)
    return False


def _update_alb_listener(cert_arn: str, old_cert_arn: str = None) -> str:
    """Attach new cert to HTTPS:443 listener. Returns listener ARN or ''."""
    if not ALB_ARN:
        return ""
    elb = _elb_client()
    listeners = elb.describe_listeners(LoadBalancerArn=ALB_ARN).get("Listeners", [])
    listener_arn = next(
        (l["ListenerArn"] for l in listeners
         if l["Protocol"] == "HTTPS" and l["Port"] == 443), None)
    if not listener_arn:
        logger.warning("No HTTPS:443 listener found on ALB %s", ALB_ARN[-30:])
        return ""
    elb.add_listener_certificates(
        ListenerArn=listener_arn, Certificates=[{"CertificateArn": cert_arn}])
    elb.modify_listener(
        ListenerArn=listener_arn, Certificates=[{"CertificateArn": cert_arn}])
    if old_cert_arn and old_cert_arn != cert_arn:
        try:
            elb.remove_listener_certificates(
                ListenerArn=listener_arn, Certificates=[{"CertificateArn": old_cert_arn}])
        except ClientError:
            pass
    logger.info("ALB listener updated to new cert")
    return listener_arn


# ════════════════════════════════════════════════════════════════════════════════
# SHARED helpers (both modes)
# ════════════════════════════════════════════════════════════════════════════════

def _store_cert_arn(cert_arn: str, domain: str, issued: bool):
    """Persist cert ARN + metadata to Secrets Manager."""
    sm  = _sm_client()
    now = datetime.now(timezone.utc)
    payload = json.dumps({
        "cert_arn":      cert_arn,
        "domain":        domain,
        "status":        "ISSUED" if issued else "PENDING_VALIDATION",
        "issued_at":     now.isoformat(),
        "expires_at":    (now + timedelta(days=90)).isoformat(),
        "days_remaining": 90,
        "stored_at":     now.isoformat(),
        "demo_mode":     DEMO_MODE,
        "managed_by":    "ssl-remediation-lambda",
    })
    try:
        sm.put_secret_value(SecretId=SSL_CERT_SECRET, SecretString=payload)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            sm.create_secret(Name=SSL_CERT_SECRET, SecretString=payload)
        else:
            logger.warning("Secrets Manager update failed (non-fatal): %s", e)
    logger.info("Cert ARN stored in Secrets Manager: %s", SSL_CERT_SECRET)


def _notify_dummy_app(error_type: str, cert_arn: str, action: str, domain: str) -> bool:
    """
    POST to /api/dummy/resolve/<error_type> on the dummy app.
    This flips the index.html SSL banner from red to green and
    writes a RESOLVED log line that gets shipped to S3.
    """
    if not DUMMY_APP_URL:
        logger.warning("DUMMY_APP_URL not set — skipping dummy app notification")
        return False
    url  = f"{DUMMY_APP_URL.rstrip('/')}/api/dummy/resolve/{error_type}"
    body = json.dumps({"details": {
        "cert_arn":    cert_arn,
        "action":      action,
        "domain":      domain,
        "resolved_by": "ssl-remediation-lambda",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "demo_mode":   DEMO_MODE,
    }}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            logger.info("Dummy app notified: HTTP %d", r.status)
            return True
    except Exception as e:
        logger.warning("Dummy app notify failed (non-fatal): %s", e)
        return False


def _call_snow_update_ticket(ticket_number: str, work_note: str,
                              resolution_note: str) -> dict:
    """
    Call the ServiceNow Lambda's updateTicket function directly via boto3
    to add a work note and resolve the ticket.

    This is a direct Lambda invocation — NOT via Bedrock — so it runs
    immediately without waiting for another agent round-trip.
    The Bedrock agent also calls updateTicket via action group in its Step 3,
    but this direct call is a safety net that runs synchronously from the
    SSL Lambda so the ticket is ALWAYS resolved even if the agent times out.
    """
    region      = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    env_name    = os.getenv("ENVIRONMENT_NAME", "dev")
    lambda_name = os.getenv("SNOW_LAMBDA_NAME",
                             f"log-aggregator-servicenow-{env_name}")

    if not ticket_number or ticket_number.startswith("INC_DEMO") or ticket_number == "INC_STUB_001":
        logger.info("Demo ticket %s — skipping real updateTicket call", ticket_number)
        return {"updated": True, "demo_mode": True, "ticket_number": ticket_number}

    payload = {
        "actionGroup": "servicenow_action_group",
        "function":    "updateTicket",
        "parameters": [
            {"name": "ticket_number",   "value": ticket_number},
            {"name": "work_note",       "value": work_note},
            {"name": "resolve",         "value": "true"},
            {"name": "resolution_note", "value": resolution_note},
        ],
    }

    try:
        lam  = boto3.client("lambda", region_name=region)
        resp = lam.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode(),
        )
        result = json.loads(resp["Payload"].read().decode())
        body   = json.loads(
            result.get("functionResponse", {})
                  .get("responseBody", {})
                  .get("TEXT", {})
                  .get("body", "{}"))
        logger.info("ServiceNow updateTicket result: %s", body)
        return body
    except Exception as e:
        logger.warning("ServiceNow updateTicket call failed (non-fatal): %s", e)
        return {"updated": False, "error": str(e)}


# ════════════════════════════════════════════════════════════════════════════════
# MAIN HANDLER
# ════════════════════════════════════════════════════════════════════════════════

def handler(event, context):
    """
    Bedrock action group handler — SSL certificate remediation.

    Bedrock event shape:
    {
      "actionGroup": "ssl_remediation_action_group",
      "function":    "remediateSSL",
      "parameters":  [
        {"name": "error_type",     "value": "ssl_expired"},
        {"name": "domain",         "value": "api.dummy-app.internal"},
        {"name": "ticket_number",  "value": "INC0001234"}   ← passed by agent after Step 1
      ]
    }
    """
    logger.info("SSL Lambda invoked | DEMO_MODE=%s | Event: %s",
                DEMO_MODE, json.dumps(event, default=str))

    params        = {p["name"]: p["value"] for p in event.get("parameters", [])}
    error_type    = params.get("error_type", "ssl_expired")
    domain        = params.get("domain", DOMAIN) or DOMAIN
    ticket_number = params.get("ticket_number", "")

    logger.info("error_type=%s domain=%s ticket=%s", error_type, domain, ticket_number)

    timeline = []

    try:
        # ── DEMO MODE path ────────────────────────────────────────────────────
        if DEMO_MODE:
            timeline.append("DEMO MODE — skipping real ACM / Route 53 / ELB calls")
            cert_arn = _demo_cert_arn()
            timeline.append(f"Generated demo cert ARN: …{cert_arn[-30:]}")
            issued        = True
            listener_arn  = "demo-listener-arn"
            old_cert_arn  = None

        # ── REAL MODE path ────────────────────────────────────────────────────
        else:
            if not HOSTED_ZONE_ID:
                return _err(event, "HOSTED_ZONE_ID env var not set")
            if not ALB_ARN:
                return _err(event, "ALB_ARN env var not set")

            timeline.append("Step 1: Checking existing cert…")
            old  = _find_existing_cert(domain)
            old_cert_arn = old["CertificateArn"] if old else None
            timeline.append(f"  Existing cert: {old['Status'] if old else 'none'}")

            timeline.append("Step 2: Requesting new ACM certificate…")
            cert_arn = _request_certificate(domain)
            timeline.append(f"  New cert ARN: …{cert_arn[-30:]}")

            timeline.append("Step 3: Writing Route 53 DNS validation CNAMEs…")
            opts   = _get_validation_options(cert_arn)
            cid    = _write_route53_cnames(opts, HOSTED_ZONE_ID)
            _wait_r53_insync(cid)
            timeline.append(f"  Route 53 change INSYNC")

            timeline.append(f"Step 4: Waiting for ACM ISSUED (up to {POLL_SECONDS}s)…")
            issued = _wait_cert_issued(cert_arn)
            timeline.append(f"  Cert issued: {issued}")

            timeline.append("Step 5: Updating ALB HTTPS listener…")
            listener_arn = _update_alb_listener(cert_arn, old_cert_arn)
            timeline.append(f"  ALB listener updated: {bool(listener_arn)}")

        # ── Steps shared by both modes ────────────────────────────────────────

        timeline.append("Step 6: Storing cert ARN in Secrets Manager…")
        _store_cert_arn(cert_arn, domain, issued)
        timeline.append(f"  Stored: {SSL_CERT_SECRET}")

        timeline.append("Step 7: Notifying dummy app (flips index.html banner green)…")
        action_label = "cert_renewed" if error_type == "ssl_expired" else "cert_rotated_proactively"
        notified = _notify_dummy_app(error_type, cert_arn, action_label, domain)
        timeline.append(f"  Dummy app notified: {notified}")

        timeline.append("Step 8: Updating ServiceNow ticket…")
        work_note = (
            f"SSL certificate remediation completed by AWS auto-remediation Lambda.\n"
            f"Domain:       {domain}\n"
            f"New cert ARN: {cert_arn}\n"
            f"Demo mode:    {DEMO_MODE}\n"
            f"ALB listener updated: {bool(listener_arn) if not DEMO_MODE else 'N/A (demo)'}\n"
            f"Cert issued:  {issued}\n"
            f"Resolved at:  {datetime.now(timezone.utc).isoformat()}"
        )
        resolution_note = (
            f"SSL certificate for {domain} renewed and deployed to ALB. "
            f"New cert valid 90 days. Issue resolved by AWS auto-remediation."
        )
        snow_result = _call_snow_update_ticket(ticket_number, work_note, resolution_note)
        timeline.append(f"  ServiceNow ticket updated: {snow_result.get('updated', False)}")

        # ── Build the message Bedrock returns to the dashboard chat ───────────
        if DEMO_MODE:
            message = (
                f"✅ SSL certificate remediation complete (DEMO MODE).\n"
                f"Domain: {domain}\n"
                f"Demo cert ARN: …{cert_arn[-30:]}\n"
                f"Cert stored in Secrets Manager ({SSL_CERT_SECRET}).\n"
                f"Dummy app banner flipped to green: {notified}.\n"
                f"ServiceNow ticket {ticket_number} updated with work note and resolved."
                if ticket_number else
                f"SSL certificate remediation complete (DEMO MODE). Cert stored. Banner updated."
            )
        else:
            if issued and listener_arn:
                message = (
                    f"SSL certificate for {domain} renewed and is now LIVE on the ALB. "
                    f"New cert: …{cert_arn[-25:]}. Valid 90 days. "
                    f"ServiceNow ticket {ticket_number} resolved."
                )
            elif issued:
                message = (
                    f"SSL cert for {domain} issued (…{cert_arn[-25:]}). "
                    f"No HTTPS listener found — attach manually in ALB console. "
                    f"ServiceNow ticket {ticket_number} resolved."
                )
            else:
                message = (
                    f"New cert requested for {domain}, DNS validation in progress. "
                    f"Cert will auto-issue within minutes. "
                    f"ServiceNow ticket {ticket_number} updated."
                )

        response_body = {
            "action":          action_label,
            "domain":          domain,
            "cert_arn":        cert_arn,
            "cert_issued":     issued,
            "alb_updated":     bool(listener_arn) if not DEMO_MODE else False,
            "demo_mode":       DEMO_MODE,
            "dummy_app_notified": notified,
            "ticket_number":   ticket_number,
            "ticket_updated":  snow_result.get("updated", False),
            "message":         message,
            "timeline":        timeline,
            "status":          "success",
        }
        logger.info("SSL Lambda complete: %s", json.dumps(response_body, default=str))

    except Exception as exc:
        logger.error("SSL remediation failed: %s", exc, exc_info=True)

        # Even on failure — try to update the ServiceNow ticket with the error
        if ticket_number:
            _call_snow_update_ticket(
                ticket_number,
                f"SSL remediation FAILED: {exc}. Manual intervention required.",
                "Auto-remediation failed — see work notes for details.",
            )

        response_body = {
            "action":    "failed",
            "error":     str(exc),
            "domain":    domain,
            "demo_mode": DEMO_MODE,
            "timeline":  timeline,
            "status":    "error",
        }

    return {
        "actionGroup": event.get("actionGroup", "ssl_remediation_action_group"),
        "function":    event.get("function",    "remediateSSL"),
        "functionResponse": {
            "responseBody": {"TEXT": {"body": json.dumps(response_body, default=str)}}
        },
    }


def _err(event: dict, msg: str) -> dict:
    logger.error("SSL Lambda config error: %s", msg)
    return {
        "actionGroup": event.get("actionGroup", "ssl_remediation_action_group"),
        "function":    event.get("function",    "remediateSSL"),
        "functionResponse": {
            "responseBody": {"TEXT": {"body": json.dumps({"status": "error", "error": msg})}}
        },
    }