import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
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

OBSERVABILITY_FUNCTION_NAME = os.getenv("OBSERVABILITY_FUNCTION_NAME", "customer-analytics-observability-agent")
STORAGE_FUNCTION_NAME = os.getenv("STORAGE_FUNCTION_NAME", "customer-analytics-storage-agent")
CRITIC_FUNCTION_NAME = os.getenv("CRITIC_FUNCTION_NAME", "customer-analytics-critic-agent")
REVISION_FUNCTION_NAME = os.getenv("REVISION_FUNCTION_NAME", "customer-analytics-hypothesis-revision-agent")
ROOT_CAUSE_FUNCTION_NAME = os.getenv("ROOT_CAUSE_FUNCTION_NAME", "customer-analytics-root-cause-assessment-agent")

BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "us.amazon.nova-2-lite-v1:0",
)

dynamodb = boto3.resource("dynamodb")
incidents_table = dynamodb.Table(INCIDENTS_TABLE_NAME)
lambda_client = boto3.client("lambda")
bedrock_runtime = boto3.client("bedrock-runtime")


HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["open", "supported", "weak", "rejected", "verified"],
                    },
                    "supporting_findings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "contradicting_findings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "hypothesis_id",
                    "statement",
                    "status",
                    "supporting_findings",
                    "contradicting_findings",
                    "confidence",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}


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
            "operation": "investigate_all",
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


def invoke_specialist(function_name, operation, incident):
    payload = {
        "operation": operation,
        "incident_id": incident["incident_id"],
        "application_id": incident["application_id"],
        "environment": incident["environment"],
        "region": incident["region"],
        "reported_symptoms": incident["reported_symptoms"],
    }
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    payload_bytes = response["Payload"].read()
    specialist_response = json.loads(payload_bytes)
    if response.get("FunctionError"):
        raise RuntimeError(f"Specialist Lambda failed: {function_name}")
    if specialist_response.get("statusCode") not in (None, 200):
        raise RuntimeError(
            f"Specialist returned status {specialist_response.get('statusCode')}: "
            f"{specialist_response.get('body')}"
        )
    body = specialist_response.get("body", specialist_response)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"raw_response": body}
    return body


def investigate_incident(incident_id):
    response = incidents_table.get_item(Key={"incident_id": incident_id})
    incident = response.get("Item")
    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")

    incident["status"] = "investigating"
    incident["updated_at"] = now_iso()
    incident["state_version"] = int(incident.get("state_version", 1)) + 1
    incident["last_event"] = "investigation_started"

    incident.setdefault("delegations", [])
    incident.setdefault("agent_findings", [])
    incident.setdefault("evidence", [])

    specialists = [
        ("observability-agent", OBSERVABILITY_FUNCTION_NAME,
         ["investigate_logs", "get_metrics", "get_alarms"]),
        ("storage-agent", STORAGE_FUNCTION_NAME,
         ["investigate_all"]),
    ]

    for agent_name, function_name, operations in specialists:
        for operation in operations:
            task = next(
                (t for t in incident.get("investigation_plan", [])
                 if t.get("operation") == operation),
                None,
            )
            if not task or task.get("status") != "pending":
                continue

            delegation = {
                "delegation_id": f"DEL-{uuid4().hex[:8].upper()}",
                "task_id": task["task_id"],
                "agent": agent_name,
                "operation": operation,
                "requested_at": now_iso(),
                "completed_at": None,
                "status": "running",
            }
            incident["delegations"].append(delegation)

            try:
                result = invoke_specialist(function_name, operation, incident)
                completed_at = now_iso()
                task["status"] = "completed"
                delegation["status"] = "completed"
                delegation["completed_at"] = completed_at

                incident["agent_findings"].append({
                    "application_id": incident["application_id"],
                    "agent": agent_name,
                    "investigation_type": result.get("investigation_type", operation),
                    "collected_at": result.get("collected_at", completed_at),
                    "resources_discovered": result.get("resources_discovered", []),
                    "findings": result.get("findings", []),
                    "evidence": result.get("evidence", {}),
                })
                incident["evidence"].append({
                    "evidence_id": f"EVD-{uuid4().hex[:8].upper()}",
                    "agent": agent_name,
                    "investigation_type": result.get("investigation_type", operation),
                    "collected_at": result.get("collected_at", completed_at),
                    "source": agent_name,
                    "summary": f"{operation} completed",
                    "artifact_uri": None,
                })
            except Exception as exc:
                logger.exception("Specialist delegation failed")
                task["status"] = "failed"
                delegation["status"] = "failed"
                delegation["completed_at"] = now_iso()
                delegation["error"] = str(exc)

    all_terminal = all(
        task.get("status") in {"completed", "failed", "skipped"}
        for task in incident.get("investigation_plan", [])
    )
    incident["status"] = "analysis" if all_terminal else "investigating"
    incident["updated_at"] = now_iso()
    incident["state_version"] = int(incident.get("state_version", 1)) + 1
    incident["last_event"] = (
        "specialist_investigation_completed"
        if all_terminal else "specialist_investigation_partial"
    )
    incidents_table.put_item(Item=incident)
    return incident


def build_reasoning_input(incident_id):
    """
    Build the controlled, read-only payload that is supplied to Bedrock.
    """
    response = incidents_table.get_item(Key={"incident_id": incident_id})
    incident = response.get("Item")
    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")

    reasoning_input = {
        "incident_id": incident["incident_id"],
        "application_id": incident["application_id"],
        "environment": incident["environment"],
        "region": incident["region"],
        "reported_symptoms": incident.get("reported_symptoms", []),
        "application_context": incident.get("application_context", {}),
        "agent_findings": incident.get("agent_findings", []),
        "evidence": incident.get("evidence", []),
        "open_questions": incident.get("open_questions", []),
    }

    return reasoning_input


def collect_valid_finding_ids(reasoning_input):
    finding_ids = set()

    for agent_result in reasoning_input.get("agent_findings", []):
        for finding in agent_result.get("findings", []):
            finding_id = finding.get("finding_id")
            if finding_id:
                finding_ids.add(finding_id)

    return finding_ids


def validate_hypotheses(payload, valid_finding_ids):
    if not isinstance(payload, dict):
        raise ValueError("Bedrock response must be a JSON object")

    hypotheses = payload.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("Bedrock response must contain a hypotheses array")

    allowed_statuses = {"open", "supported", "weak", "rejected", "verified"}

    for index, hypothesis in enumerate(hypotheses):
        if not isinstance(hypothesis, dict):
            raise ValueError(f"hypotheses[{index}] must be an object")

        required_fields = {
            "hypothesis_id",
            "statement",
            "status",
            "supporting_findings",
            "contradicting_findings",
            "confidence",
            "rationale",
        }
        missing = required_fields - set(hypothesis)
        if missing:
            raise ValueError(
                f"hypotheses[{index}] missing required fields: {sorted(missing)}"
            )

        if hypothesis["status"] not in allowed_statuses:
            raise ValueError(
                f"hypotheses[{index}] has invalid status: {hypothesis['status']}"
            )

        confidence = hypothesis["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError(
                f"hypotheses[{index}].confidence must be a number"
            )
        if not 0 <= confidence <= 1:
            raise ValueError(
                f"hypotheses[{index}].confidence must be between 0 and 1"
            )

        for field in ("supporting_findings", "contradicting_findings"):
            references = hypothesis[field]
            if not isinstance(references, list):
                raise ValueError(
                    f"hypotheses[{index}].{field} must be an array"
                )

            unknown = [
                reference
                for reference in references
                if reference not in valid_finding_ids
            ]
            if unknown:
                raise ValueError(
                    f"hypotheses[{index}] references unknown finding IDs: {unknown}"
                )

    return hypotheses


def invoke_bedrock_reasoning(reasoning_input):
    system_prompt = """
You are the reasoning layer of an AWS CloudOps multi-agent system.

Your job is to analyze the supplied incident context and specialist evidence and
produce causal hypotheses.

Strict rules:
1. Reason ONLY from the supplied input.
2. Do not invent telemetry, metrics, logs, resources, alarms, or events.
3. A missing metric datapoint is NOT evidence that the metric value was zero.
4. A finding marked informational does not by itself prove a root cause.
5. Distinguish observed facts from causal hypotheses.
6. When evidence is insufficient, keep hypotheses open and explain the uncertainty.
7. You may produce multiple plausible hypotheses when the evidence does not
   distinguish between them.
8. supporting_findings and contradicting_findings MUST contain only finding_id
   values present in the supplied agent findings.
9. Confidence is a reasoning confidence from 0 to 1, not a calibrated probability.
10. Do not propose destructive remediation actions. This stage is analysis only.
11. Return ONLY valid JSON. Do not use Markdown fences or commentary outside the JSON object.
12. The JSON must contain a top-level "hypotheses" array.
13. Each hypothesis must contain hypothesis_id, statement, status, supporting_findings, contradicting_findings, confidence, and rationale.
""".strip()

    user_prompt = (
        "Analyze this incident using only the supplied evidence. "
        "Return hypotheses that could explain the reported symptoms.

"
        + json.dumps(reasoning_input, default=str)
    )

    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [{"text": user_prompt}],
            }
        ],
        inferenceConfig={
            "maxTokens": 1800,
            "temperature": 0.0,
        },
    )

    content = response.get("output", {}).get("message", {}).get("content", [])
    text_parts = [block["text"] for block in content if "text" in block]
    if not text_parts:
        raise ValueError("Bedrock returned no text content")

    model_text = "".join(text_parts).strip()

    if model_text.startswith("```"):
        lines = model_text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        model_text = "\n".join(lines).strip()

    try:
        return json.loads(model_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Bedrock returned invalid JSON: {model_text}"
        ) from exc


def generate_hypotheses(incident_id):
    response = incidents_table.get_item(Key={"incident_id": incident_id})
    incident = response.get("Item")
    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")

    reasoning_input = build_reasoning_input(incident_id)
    valid_finding_ids = collect_valid_finding_ids(reasoning_input)

    model_output = invoke_bedrock_reasoning(reasoning_input)
    hypotheses = validate_hypotheses(model_output, valid_finding_ids)

    persisted_hypotheses = []
    for hypothesis in hypotheses:
        stored = dict(hypothesis)
        stored["confidence"] = Decimal(str(hypothesis["confidence"]))
        persisted_hypotheses.append(stored)

    incident["hypotheses"] = persisted_hypotheses
    incident["status"] = "analysis"
    incident["updated_at"] = now_iso()
    incident["state_version"] = int(incident.get("state_version", 1)) + 1
    incident["last_event"] = "hypotheses_generated"
    incidents_table.put_item(Item=incident)

    return persisted_hypotheses



def map_required_investigation(description):
    """
    Deterministically map a Root Cause Agent evidence request to an
    existing specialist operation.

    The Root Cause Agent describes the evidence gap.
    The Manager decides which specialist operation can collect it.
    """
    text = description.lower()
    operations = []

    if any(term in text for term in [
        "s3",
        "upload",
        "server access logs",
        "error responses",
    ]):
        operations.append({
            "agent": "storage-agent",
            "operation": "investigate_s3",
        })

    if any(term in text for term in [
        "cloudwatch logs",
        "lambda invocation logs",
        "lambda logs",
    ]):
        operations.append({
            "agent": "observability-agent",
            "operation": "investigate_logs",
        })

    if any(term in text for term in [
        "eventbridge",
        "event delivery",
        "event pattern",
        "rule invocation",
        "delivery attempts",
        "events history",
    ]):
        operations.append({
            "agent": "storage-agent",
            "operation": "investigate_eventbridge",
        })

    if any(term in text for term in [
        "invocation pattern",
        "lambda function configuration",
        "expected invocation",
    ]):
        operations.append({
            "agent": "observability-agent",
            "operation": "get_metrics",
        })

    return operations


def create_targeted_investigation_tasks(
    incident,
    required_investigations,
):
    """
    Convert Root Cause Agent evidence gaps into concrete specialist
    tasks.

    A targeted investigation is allowed to repeat an operation that
    was already executed during an earlier investigation round.

    Deduplication happens only within the current round, so a second
    Root Cause Assessment can legitimately request fresh evidence.
    """
    current_round = int(
        incident.get(
            "targeted_investigation_round",
            0,
        )
    ) + 1

    # Safety guard against an endless investigation loop.
    if current_round > 2:
        raise ValueError(
            "Maximum targeted investigation rounds reached"
        )

    incident["targeted_investigation_round"] = current_round

    existing_this_round = {
        (
            task.get("agent"),
            task.get("operation"),
            task.get("reason"),
        )
        for task in incident.get(
            "investigation_plan",
            [],
        )
        if task.get("source") == "root_cause_assessment"
        and int(task.get("investigation_round", 0)) == current_round
    }

    created_tasks = []

    for description in required_investigations:
        if not isinstance(description, str) or not description.strip():
            continue

        mappings = map_required_investigation(description)

        for mapping in mappings:
            agent = mapping["agent"]
            operation = mapping["operation"]

            key = (
                agent,
                operation,
                description,
            )

            if key in existing_this_round:
                continue

            task = {
                "task_id": f"TASK-{uuid4().hex[:8].upper()}",
                "agent": agent,
                "operation": operation,
                "status": "pending",
                "created_at": now_iso(),
                "source": "root_cause_assessment",
                "investigation_round": current_round,
                "reason": description,
            }

            incident.setdefault(
                "investigation_plan",
                [],
            ).append(task)

            existing_this_round.add(key)
            created_tasks.append(task)

    return created_tasks


def delegate_targeted_task(
    incident,
    task,
):
    """
    Invoke a specialist for one targeted investigation.
    """
    specialist_functions = {
        "observability-agent": OBSERVABILITY_FUNCTION_NAME,
        "storage-agent": STORAGE_FUNCTION_NAME,
    }

    allowed_operations = {
        "observability-agent": {
            "investigate_logs",
            "get_metrics",
            "get_alarms",
        },
        "storage-agent": {
            "investigate_all",
            "investigate_s3",
            "investigate_dynamodb",
            "investigate_eventbridge",
        },
    }

    agent = task["agent"]
    operation = task["operation"]

    if agent not in specialist_functions:
        raise ValueError(
            f"Unsupported specialist agent: {agent}"
        )

    if operation not in allowed_operations[agent]:
        raise ValueError(
            f"Unsupported operation '{operation}' for agent '{agent}'"
        )

    delegation = {
        "delegation_id": f"DEL-{uuid4().hex[:8].upper()}",
        "task_id": task["task_id"],
        "agent": agent,
        "operation": operation,
        "requested_at": now_iso(),
        "completed_at": None,
        "status": "running",
        "source": "root_cause_assessment",
        "reason": task.get("reason"),
        "investigation_round": task.get("investigation_round"),
    }

    task["status"] = "running"

    try:
        result = invoke_specialist(
            specialist_functions[agent],
            operation,
            incident,
        )

        completed_at = now_iso()

        task["status"] = "completed"
        delegation["status"] = "completed"
        delegation["completed_at"] = completed_at

        incident.setdefault(
            "agent_findings",
            [],
        ).append({
            "application_id": incident["application_id"],
            "agent": agent,
            "operation": operation,
            "investigation_type": result.get(
                "investigation_type",
                operation,
            ),
            "collected_at": result.get(
                "collected_at",
                completed_at,
            ),
            "source": "targeted_investigation",
            "reason": task.get("reason"),
            "investigation_round": task.get(
                "investigation_round"
            ),
            "resources_discovered": result.get(
                "resources_discovered",
                [],
            ),
            "findings": result.get(
                "findings",
                [],
            ),
            "evidence": result.get(
                "evidence",
                {},
            ),
        })

        incident.setdefault(
            "evidence",
            [],
        ).append({
            "evidence_id": f"EVD-{uuid4().hex[:8].upper()}",
            "agent": agent,
            "operation": operation,
            "investigation_type": result.get(
                "investigation_type",
                operation,
            ),
            "collected_at": result.get(
                "collected_at",
                completed_at,
            ),
            "source": "targeted_investigation",
            "summary": f"{operation} completed",
            "artifact_uri": None,
            "investigation_round": task.get(
                "investigation_round"
            ),
        })

        return {
            "task": task,
            "delegation": delegation,
            "result": result,
        }

    except Exception as exc:
        logger.exception(
            "Targeted specialist delegation failed"
        )

        task["status"] = "failed"
        delegation["status"] = "failed"
        delegation["completed_at"] = now_iso()
        delegation["error"] = str(exc)

        return {
            "task": task,
            "delegation": delegation,
            "error": str(exc),
        }


def assess_root_cause(incident_id):
    """
    Invoke the Root Cause Assessment Agent.

    If it reports insufficient evidence, the Manager converts its
    required investigations into concrete specialist tasks and
    executes them.

    The Manager does not invent investigation results.
    """
    response = incidents_table.get_item(
        Key={"incident_id": incident_id}
    )
    incident = response.get("Item")

    if not incident:
        raise ValueError(
            f"Incident not found: {incident_id}"
        )

    root_cause_response = invoke_specialist(
        ROOT_CAUSE_FUNCTION_NAME,
        "assess_root_cause",
        incident,
    )

    assessment = root_cause_response.get(
        "root_cause_assessment"
    )

    if not isinstance(assessment, dict):
        raise ValueError(
            "Root Cause Assessment Agent did not return "
            "root_cause_assessment"
        )

    incident["root_cause_assessment"] = assessment
    incident["updated_at"] = now_iso()
    incident["state_version"] = (
        int(incident.get("state_version", 1)) + 1
    )

    assessment_status = assessment.get("status")

    if assessment_status in {
        "root_cause_supported",
        "multiple_plausible_causes",
    }:
        incident["status"] = "analysis"
        incident["last_event"] = (
            "root_cause_assessment_completed"
        )

        incidents_table.put_item(Item=incident)

        return incident

    if assessment_status != "insufficient_evidence":
        raise ValueError(
            "Unsupported Root Cause Assessment status: "
            f"{assessment_status}"
        )

    required_investigations = assessment.get(
        "required_investigations",
        [],
    )

    if not isinstance(required_investigations, list):
        raise ValueError(
            "required_investigations must be a list"
        )

    targeted_tasks = create_targeted_investigation_tasks(
        incident,
        required_investigations,
    )

    incident.setdefault(
        "delegations",
        [],
    )

    incident["status"] = "investigating"
    incident["updated_at"] = now_iso()
    incident["state_version"] = (
        int(incident.get("state_version", 1)) + 1
    )
    incident["last_event"] = (
        "targeted_investigations_planned"
    )

    incidents_table.put_item(Item=incident)

    targeted_results = []

    for task in targeted_tasks:
        result = delegate_targeted_task(
            incident,
            task,
        )

        incident["delegations"].append(
            result["delegation"]
        )

        targeted_results.append({
            "task_id": task["task_id"],
            "agent": task["agent"],
            "operation": task["operation"],
            "status": task["status"],
            "reason": task.get("reason"),
            "investigation_round": task.get(
                "investigation_round"
            ),
            "success": result.get("result") is not None,
        })

    incident["status"] = "analysis"
    incident["updated_at"] = now_iso()
    incident["state_version"] = (
        int(incident.get("state_version", 1)) + 1
    )
    incident["last_event"] = (
        "targeted_investigation_completed"
    )

    incidents_table.put_item(Item=incident)

    return {
        "incident_id": incident_id,
        "status": incident["status"],
        "root_cause_assessment": assessment,
        "targeted_investigations": targeted_results,
        "targeted_investigation_round": incident.get(
            "targeted_investigation_round",
            0,
        ),
        "agent_findings": incident.get(
            "agent_findings",
            [],
        ),
        "evidence": incident.get(
            "evidence",
            [],
        ),
    }

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

    if operation not in {
        "create_incident",
        "investigate_incident",
        "build_reasoning_input",
        "generate_hypotheses",
        "assess_root_cause",
    }:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Unsupported operation",
                "supported_operations": [
                    "create_incident",
                    "investigate_incident",
                    "build_reasoning_input",
                    "generate_hypotheses",
                    "assess_root_cause",
                ],
            }),
        }

    try:
        if operation == "create_incident":
            incident = create_incident(event)
            return {
                "statusCode": 201,
                "body": json.dumps({
                    "message": "Incident created",
                    "incident": incident,
                }, default=str),
            }

        incident_id = event.get("incident_id")
        if not incident_id:
            raise ValueError(f"incident_id is required for {operation}")

        if operation == "investigate_incident":
            incident = investigate_incident(incident_id)
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Incident investigation completed",
                    "incident": incident,
                }, default=str),
            }

        if operation == "assess_root_cause":
            incident = assess_root_cause(incident_id)
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Root cause assessment completed",
                    "incident": incident,
                }, default=str),
            }

        if operation == "build_reasoning_input":
            reasoning_input = build_reasoning_input(incident_id)
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Reasoning input built",
                    "reasoning_input": reasoning_input,
                }, default=str),
            }

        hypotheses = generate_hypotheses(incident_id)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Hypotheses generated",
                "model_id": BEDROCK_MODEL_ID,
                "hypotheses": hypotheses,
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
                "message": exc.response.get("Error", {}).get("Message"),
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
