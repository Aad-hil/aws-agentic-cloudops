import json
import logging
import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE = os.getenv("INCIDENTS_TABLE_NAME", "customer-analytics-incidents")
MODEL = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")

table = boto3.resource("dynamodb").Table(TABLE)
bedrock = boto3.client("bedrock-runtime")

ASSESSMENT_STATUSES = {
    "root_cause_supported",
    "insufficient_evidence",
    "multiple_plausible_causes",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def get_incident(incident_id):
    item = table.get_item(Key={"incident_id": incident_id}).get("Item")
    if not item:
        raise ValueError("Incident not found: %s" % incident_id)
    return item


def finding_ids(incident):
    return {
        finding["finding_id"]
        for result in incident.get("agent_findings", [])
        for finding in result.get("findings", [])
        if finding.get("finding_id")
    }


def hypothesis_map(incident):
    return {
        h["hypothesis_id"]: h
        for h in incident.get("hypotheses", [])
        if h.get("hypothesis_id")
    }


def build_input(incident):
    return {
        "incident_id": incident["incident_id"],
        "application_id": incident["application_id"],
        "environment": incident["environment"],
        "region": incident["region"],
        "reported_symptoms": incident.get("reported_symptoms", []),
        "application_context": incident.get("application_context", {}),
        "agent_findings": incident.get("agent_findings", []),
        "evidence": incident.get("evidence", []),
        "hypotheses": incident.get("hypotheses", []),
        "hypothesis_critiques": incident.get("hypothesis_critiques", []),
        "hypothesis_revision_history": incident.get("hypothesis_revision_history", []),
        "open_questions": incident.get("open_questions", []),
    }


def invoke_model(data):
    system = """You are the Root Cause Assessment Agent in an AWS CloudOps multi-agent system.

Your job is to determine whether the supplied evidence is sufficient to establish a root cause.

You are NOT a hypothesis-generation agent.

STRICT RULES:
1. Reason only from the supplied incident state.
2. Do not create new hypotheses.
3. Do not introduce a causal explanation absent from the supplied hypotheses or evidence.
4. Preserve existing hypothesis IDs.
5. A weak or open hypothesis cannot be declared a supported root cause without additional evidence.
6. A rejected hypothesis cannot be selected as a root cause.
7. Missing telemetry is NOT evidence of zero activity.
8. An enabled resource is NOT proof that the resource is functioning correctly.
9. Accessibility is NOT proof of correct IAM authorization.
10. Correlation is NOT sufficient for causal attribution.
11. If evidence is insufficient, identify the evidence gaps.
12. If more AWS evidence is required, describe targeted investigations rather than inventing their results.
13. Do not rank or score competing hypotheses.
14. Do not propose remediation actions.
15. Do not claim a root cause is verified unless the supplied evidence establishes it.

ALLOWED ASSESSMENT STATUSES:
- root_cause_supported
- insufficient_evidence
- multiple_plausible_causes

OUTPUT:
Return ONLY valid JSON.
Return exactly one top-level key: root_cause_assessment.

The object must contain:
status
candidate_hypothesis_ids
root_cause_statement
supporting_findings
contradicting_findings
evidence_gaps
required_investigations
rationale

For root_cause_supported:
- candidate_hypothesis_ids must contain exactly one existing hypothesis ID.
- root_cause_statement must describe that existing hypothesis only.

For multiple_plausible_causes:
- candidate_hypothesis_ids must contain at least two existing, non-rejected hypothesis IDs.
- Do not rank them.

For insufficient_evidence:
- candidate_hypothesis_ids may contain unresolved existing hypothesis IDs.
- root_cause_statement must be null.

All finding references must be existing finding IDs.
Do not invent finding IDs.
""".strip()

    response = bedrock.converse(
        modelId=MODEL,
        system=[{"text": system}],
        messages=[{
            "role": "user",
            "content": [{
                "text": "Assess the current evidence. Do not generate a new hypothesis.\n"
                        + json.dumps(data, default=str)
            }]
        }],
        inferenceConfig={"maxTokens": 1800, "temperature": 0.0},
    )

    parts = [
        block["text"]
        for block in response.get("output", {}).get("message", {}).get("content", [])
        if "text" in block
    ]

    if not parts:
        raise ValueError("Bedrock returned no text content")

    raw_text = "".join(parts).strip()
    logger.info("Root Cause Assessment raw Bedrock output: %s", raw_text)

    text = raw_text

    if not text.startswith("{"):
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Root Cause Assessment invalid JSON: %s", text)
        raise ValueError("Bedrock returned invalid JSON: %s" % text) from exc

    if not isinstance(payload, dict):
        raise ValueError("Bedrock response must be a JSON object")

    return payload


def validate(payload, incident):
    assessment = payload.get("root_cause_assessment") if isinstance(payload, dict) else None

    if not isinstance(assessment, dict):
        raise ValueError("Bedrock response must contain root_cause_assessment")

    required = {
        "status",
        "candidate_hypothesis_ids",
        "root_cause_statement",
        "supporting_findings",
        "contradicting_findings",
        "evidence_gaps",
        "required_investigations",
        "rationale",
    }

    missing = required - set(assessment)
    if missing:
        raise ValueError("root_cause_assessment missing fields: %s" % sorted(missing))

    status = assessment["status"]
    if status not in ASSESSMENT_STATUSES:
        raise ValueError("Invalid root cause assessment status")

    hypotheses = hypothesis_map(incident)
    candidate_ids = assessment["candidate_hypothesis_ids"]

    if not isinstance(candidate_ids, list):
        raise ValueError("candidate_hypothesis_ids must be an array")

    unknown_hypotheses = [h for h in candidate_ids if h not in hypotheses]
    if unknown_hypotheses:
        raise ValueError("Unknown hypothesis IDs: %s" % unknown_hypotheses)

    if status == "root_cause_supported":
        if len(candidate_ids) != 1:
            raise ValueError("root_cause_supported requires exactly one candidate hypothesis")

        selected = hypotheses[candidate_ids[0]]

        if selected.get("status") in {"rejected", "weak", "open"}:
            raise ValueError(
                "A rejected, weak, or open hypothesis cannot be a supported root cause"
            )

        if not isinstance(assessment["root_cause_statement"], str):
            raise ValueError(
                "root_cause_statement must be a string for root_cause_supported"
            )

    elif status == "multiple_plausible_causes":
        if len(candidate_ids) < 2:
            raise ValueError("multiple_plausible_causes requires at least two candidates")

        rejected = [
            h for h in candidate_ids
            if hypotheses[h].get("status") == "rejected"
        ]

        if rejected:
            raise ValueError(
                "Rejected hypotheses cannot be candidates: %s" % rejected
            )

        if assessment["root_cause_statement"] is not None:
            raise ValueError(
                "root_cause_statement must be null for multiple_plausible_causes"
            )

    elif status == "insufficient_evidence":
        if assessment["root_cause_statement"] is not None:
            raise ValueError(
                "root_cause_statement must be null for insufficient_evidence"
            )

    valid_findings = finding_ids(incident)

    for field in ("supporting_findings", "contradicting_findings"):
        value = assessment[field]

        if not isinstance(value, list):
            raise ValueError("%s must be an array" % field)

        unknown = [f for f in value if f not in valid_findings]

        if unknown:
            raise ValueError(
                "Unknown finding IDs in %s: %s" % (field, unknown)
            )

    for field in ("evidence_gaps", "required_investigations"):
        if not isinstance(assessment[field], list):
            raise ValueError("%s must be an array" % field)

        if not all(isinstance(item, str) for item in assessment[field]):
            raise ValueError("%s must contain strings" % field)

    if not isinstance(assessment["rationale"], str):
        raise ValueError("rationale must be a string")

    return assessment


def assess(incident_id):
    incident = get_incident(incident_id)

    if not incident.get("hypotheses"):
        raise ValueError(
            "No hypotheses exist. Generate and revise hypotheses first."
        )

    assessment = validate(
        invoke_model(build_input(incident)),
        incident,
    )

    incident["root_cause_assessment"] = assessment
    incident["status"] = "analysis"
    incident["updated_at"] = now()
    incident["state_version"] = int(incident.get("state_version", 1)) + 1
    incident["last_event"] = "root_cause_assessment_completed"

    table.put_item(Item=incident)

    return assessment


def lambda_handler(event, context):
    if event.get("operation", "assess_root_cause") != "assess_root_cause":
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Unsupported operation",
                "supported_operations": ["assess_root_cause"],
            }),
        }

    incident_id = event.get("incident_id")

    if not incident_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "incident_id is required"}),
        }

    try:
        result = assess(incident_id)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "incident_id": incident_id,
                "model_id": MODEL,
                "status": "analysis",
                "root_cause_assessment": result,
            }, default=str),
        }

    except ValueError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(exc)}),
        }

    except ClientError as exc:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "AWS operation failed",
                "code": exc.response.get("Error", {}).get("Code"),
                "message": exc.response.get("Error", {}).get("Message"),
            }),
        }

    except Exception:
        logger.exception("Unexpected Root Cause Assessment Agent failure")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Unexpected Root Cause Assessment Agent failure",
            }),
        }
