import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INCIDENTS_TABLE_NAME = os.getenv(
    "INCIDENTS_TABLE_NAME",
    "customer-analytics-incidents",
)
REGISTRY_FUNCTION_NAME = os.getenv(
    "REGISTRY_FUNCTION_NAME",
    "customer-analytics-registry-api",
)
DEFAULT_ENVIRONMENT = os.getenv("DEFAULT_ENVIRONMENT", "poc")
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb")
incidents_table = dynamodb.Table(INCIDENTS_TABLE_NAME)
lambda_client = boto3.client("lambda")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def generate_incident_id():
    # Human-readable prefix plus UUID fragment keeps IDs unique for the POC.
    return f"INC-{uuid4().hex[:8].upper()}"


def invoke_registry(application_id):
    response = lambda_client.invoke(
        FunctionName=REGISTRY_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "operation": "get_application",
            "application_id": application_id,
        }).encode("utf-8"),
    )

    payload = response["Payload"].read()
    registry_response = json.loads(payload)

    if registry_response.get("statusCode") != 200:
        body = registry_response.get("body", "{}")
        try:
            body = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            pass

        raise ValueError(
            f"Application registry lookup failed: {body}"
        )

    body = registry_response.get("body", "{}")
    return json.loads(body)


def build_investigation_plan(reported_symptoms):
    # Deterministic v1 plan. Bedrock-based planning comes later.
    symptoms_text = " ".join(reported_symptoms).lower()

    plan = [
        {
            "task_id": "TASK-001",
            "agent": "observability-agent",
            "operation": "investigate_logs",
            "status": "pending",
        },
        {
            "task_id": "TASK-002",
            "agent": "observability-agent",
            "operation": "get_metrics",
            "status": "pending",
        },
        {
            "task_id": "TASK-003",
            "agent": "observability-agent",
            "operation": "get_alarms",
            "status": "pending",
        },
        {
            "task_id": "TASK-004",
            "agent": "storage-agent",
            "operation": "investigate_storage",
            "status": "pending",
        },
    ]

    # Keep the v1 plan broad enough to establish the multi-agent workflow.
    # Later, the Manager/Bedrock planner will select tasks from the symptoms.
    if "cloudwatch" not in symptoms_text:
        plan = [task for task in plan if task["operation"] != "get_alarms"]

    created_at = now_iso()
    for task in plan:
        task["created_at"] = created_at

    return plan


def create_incident(event):
    application_id = event.get("application_id")
    if not application_id:
        raise ValueError("application_id is required")

    reported_symptoms = event.get("reported_symptoms")
    if not isinstance(reported_symptoms, list) or not reported_symptoms:
        raise ValueError("reported_symptoms must be a non-empty list")

    severity = event.get("severity", "medium")
    allowed_severities = {"low", "medium", "high", "critical"}
    if severity not in allowed_severities:
        raise ValueError(
            f"severity must be one of: {sorted(allowed_severities)}"
        )

    application = invoke_registry(application_id)

    created_at = now_iso()
    incident_id = event.get("incident_id") or generate_incident_id()
    investigation_plan = build_investigation_plan(reported_symptoms)

    item = {
        "incident_id": incident_id,
        "application_id": application_id,
        "environment": application.get(
            "environment",
            event.get("environment", DEFAULT_ENVIRONMENT),
        ),
        "region": application.get(
            "region",
            event.get("region", DEFAULT_REGION),
        ),
        "status": "planning",
        "severity": severity,
        "reported_symptoms": reported_symptoms,
        "created_at": created_at,
        "updated_at": created_at,
        "state_version": 2,
        "application_context": {
            "name": application.get("name"),
            "resource_count": len(application.get("resources", [])),
            "dependency_count": len(application.get("dependencies", [])),
        },
        "investigation_plan": investigation_plan,
        "delegations": [],
        "agent_findings": [],
        "evidence": [],
        "hypotheses": [],
        "open_questions": [],
        "actions": [],
        "decision": None,
        "approval": {
            "required": False,
            "status": "not_required",
        },
        "remediation": None,
        "verification": None,
        "last_event": "investigation_plan_created",
    }

    incidents_table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(incident_id)",
    )

    logger.info(
        json.dumps({
            "event": "incident_created",
            "incident_id": incident_id,
            "application_id": application_id,
            "status": item["status"],
            "plan_task_count": len(investigation_plan),
        })
    )

    return item


def lambda_handler(event, context):
    logger.info(
        json.dumps({
            "event": "manager_request_received",
            "request_id": context.aws_request_id,
            "event_payload": event,
        })
    )

    operation = event.get("operation", "create_incident")

    if operation != "create_incident":
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Unsupported operation",
                "supported_operations": ["create_incident"],
            }),
        }

    try:
        incident = create_incident(event)

        return {
            "statusCode": 201,
            "body": json.dumps({
                "message": "Incident created",
                "incident": incident,
            }, default=str),
        }

    except ValueError as exc:
        logger.warning("Invalid manager request: %s", exc)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(exc)}),
        }

    except ClientError as exc:
        logger.exception("AWS operation failed")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "AWS operation failed",
                "code": exc.response.get("Error", {}).get("Code"),
            }),
        }

    except Exception:
        logger.exception("Unexpected CloudOps Manager failure")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Unexpected CloudOps Manager failure",
            }),
        }
