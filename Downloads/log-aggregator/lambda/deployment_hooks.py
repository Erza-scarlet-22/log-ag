# ──────────────────────────────────────────────────────────────────────────────
# lambda/deployment_hooks.py  –  CodeDeploy lifecycle hook Lambdas
#
# Two functions in this file (deploy separately or as one multi-handler Lambda):
#
#   pretraffic_hook   – BeforeAllowTraffic: validates the new ECS/Lambda version
#   posttraffic_hook  – AfterAllowTraffic:  emits deployment success metrics
#
# CodeDeploy invokes these with a payload like:
#   {
#     "DeploymentId": "d-XXXXXXX",
#     "LifecycleEventHookExecutionId": "eyJlbm..."
#   }
#
# CRITICAL: Both hooks MUST call codedeploy.put_lifecycle_event_hook_execution_status
# with either "Succeeded" or "Failed" — otherwise CodeDeploy will time out.
# ──────────────────────────────────────────────────────────────────────────────

import json
import logging
import os
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

codedeploy  = boto3.client("codedeploy")
cloudwatch  = boto3.client("cloudwatch")

# Health check URL for the green (new) ECS task set
# Set this as an environment variable in the hook Lambda's configuration
HEALTH_CHECK_URL = os.environ.get(
    "HEALTH_CHECK_URL",
    "http://localhost:5000/api/status",   # Override with real ALB test listener URL
)


def pretraffic_hook(event, context):
    """
    BeforeAllowTraffic hook.
    Runs BEFORE CodeDeploy shifts any traffic to the new deployment.
    Validates the new version by hitting its health endpoint.
    """
    deployment_id      = event["DeploymentId"]
    hook_execution_id  = event["LifecycleEventHookExecutionId"]
    logger.info("PreTraffic hook — DeploymentId: %s", deployment_id)

    status = "Succeeded"
    try:
        _validate_health(HEALTH_CHECK_URL)
        logger.info("Health check passed for deployment %s", deployment_id)
    except Exception as exc:
        logger.error("Health check FAILED: %s", exc)
        status = "Failed"

    _report_status(deployment_id, hook_execution_id, status)
    return {"status": status}


def posttraffic_hook(event, context):
    """
    AfterAllowTraffic hook.
    Runs AFTER 100% traffic has shifted to the new deployment.
    Emits a custom CloudWatch metric to confirm successful deployment.
    """
    deployment_id      = event["DeploymentId"]
    hook_execution_id  = event["LifecycleEventHookExecutionId"]
    logger.info("PostTraffic hook — DeploymentId: %s", deployment_id)

    status = "Succeeded"
    try:
        cloudwatch.put_metric_data(
            Namespace="LogAggregator/Deployments",
            MetricData=[
                {
                    "MetricName": "SuccessfulDeployment",
                    "Value":      1,
                    "Unit":       "Count",
                    "Dimensions": [
                        {"Name": "DeploymentId", "Value": deployment_id}
                    ],
                }
            ],
        )
        logger.info("Deployment success metric emitted for %s", deployment_id)
    except Exception as exc:
        logger.error("PostTraffic metric emission failed: %s", exc)
        # Don't fail the deployment just for a metric error
        # status = "Failed"

    _report_status(deployment_id, hook_execution_id, status)
    return {"status": status}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_health(url: str, timeout: int = 10):
    """Perform a simple HTTP health check. Raises on non-200 or network error."""
    logger.info("Health check -> %s", url)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Health check returned HTTP {resp.status}")
        body = resp.read().decode()
        logger.info("Health check response: %s", body[:200])


def _report_status(deployment_id: str, hook_execution_id: str, status: str):
    """Report hook result back to CodeDeploy. Must be called in every code path."""
    logger.info("Reporting %s to CodeDeploy for deployment %s", status, deployment_id)
    codedeploy.put_lifecycle_event_hook_execution_status(
        deploymentId=deployment_id,
        lifecycleEventHookExecutionId=hook_execution_id,
        status=status,
    )
