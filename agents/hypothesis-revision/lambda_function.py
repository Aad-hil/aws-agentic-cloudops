import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)
TABLE = os.getenv("INCIDENTS_TABLE_NAME", "customer-analytics-incidents")
MODEL = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
MAX_REVISIONS = 2

table = boto3.resource("dynamodb").Table(TABLE)
bedrock = boto3.client("bedrock-runtime")
STATUSES = {"open", "supported", "weak", "rejected", "verified"}

def now():
    return datetime.now(timezone.utc).isoformat()

def get_incident(incident_id):
    item = table.get_item(Key={"incident_id": incident_id}).get("Item")
    if not item:
        raise ValueError("Incident not found: %s" % incident_id)
    return item

def finding_ids(incident):
    return {
        f["finding_id"]
        for result in incident.get("agent_findings", [])
        for f in result.get("findings", [])
        if f.get("finding_id")
    }

def build_input(incident, revision_number):
    return {
        "revision_number": revision_number,
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
        "open_questions": incident.get("open_questions", []),
    }

def invoke_model(data):
    system = """You are the Hypothesis Revision Agent in an AWS CloudOps multi-agent system.
Revise current hypotheses after independent Critic feedback.
Reason only from supplied incident state. Critic feedback is a challenge, not ground truth.
Never invent telemetry, resources, metrics, logs, alarms, events, or finding IDs.
Missing telemetry is not zero activity. Informational findings do not prove causality.
Remove unsupported evidence references. Preserve hypothesis_id values.
Return exactly one hypothesis for every current hypothesis.
Do not perform AWS actions or propose remediation.
Return only JSON with a top-level hypotheses array.
Each hypothesis requires hypothesis_id, statement, status, supporting_findings,
contradicting_findings, confidence, and rationale.
Confidence must be a number from 0 to 1.
""".strip()
    response = bedrock.converse(
        modelId=MODEL,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": json.dumps(data, default=str)}]}],
        inferenceConfig={"maxTokens": 1800, "temperature": 0.0},
    )
    parts = [b["text"] for b in response.get("output", {}).get("message", {}).get("content", []) if "text" in b]
    if not parts:
        raise ValueError("Bedrock returned no text content")
    text = "".join(parts).strip()
    if text.startswith("```"):
        rows = text.splitlines()
        text = "\n".join(rows[1:-1] if rows[-1].strip() == "```" else rows[1:]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Bedrock returned invalid JSON: %s" % text) from exc

def validate(payload, incident):
    hypotheses = payload.get("hypotheses") if isinstance(payload, dict) else None
    current = incident.get("hypotheses", [])
    if not isinstance(hypotheses, list):
        raise ValueError("Bedrock response must contain a hypotheses array")
    if [x.get("hypothesis_id") for x in hypotheses] != [x.get("hypothesis_id") for x in current]:
        raise ValueError("Revision must preserve hypothesis IDs exactly")
    valid = finding_ids(incident)
    required = {"hypothesis_id","statement","status","supporting_findings","contradicting_findings","confidence","rationale"}
    for i, h in enumerate(hypotheses):
        missing = required - set(h)
        if missing:
            raise ValueError("hypotheses[%d] missing fields: %s" % (i, sorted(missing)))
        if h["status"] not in STATUSES:
            raise ValueError("Invalid hypothesis status")
        if isinstance(h["confidence"], bool) or not isinstance(h["confidence"], (int,float)) or not 0 <= h["confidence"] <= 1:
            raise ValueError("confidence must be a number between 0 and 1")
        for field in ("supporting_findings","contradicting_findings"):
            if not isinstance(h[field], list):
                raise ValueError("%s must be an array" % field)
            unknown = [x for x in h[field] if x not in valid]
            if unknown:
                raise ValueError("Unknown finding IDs: %s" % unknown)
    return hypotheses

def revise(incident_id):
    incident = get_incident(incident_id)
    if not incident.get("hypotheses"):
        raise ValueError("No hypotheses exist. Generate hypotheses first.")
    if not incident.get("hypothesis_critiques"):
        raise ValueError("No critiques exist. Run the Critic Agent first.")
    history = incident.get("hypothesis_revision_history", [])
    if len(history) >= MAX_REVISIONS:
        raise ValueError("Maximum hypothesis revisions reached: %d" % MAX_REVISIONS)
    number = len(history) + 1
    revised = validate(invoke_model(build_input(incident, number)), incident)
    stored = []
    for h in revised:
        item = dict(h)
        item["confidence"] = Decimal(str(h["confidence"]))
        stored.append(item)
    history.append({
        "revision_number": number,
        "created_at": now(),
        "hypotheses": stored,
        "critic_verdicts": [
            {"hypothesis_id": c["hypothesis_id"], "verdict": c["verdict"], "confidence": Decimal(str(c["confidence"]))}
            for c in incident.get("hypothesis_critiques", [])
        ],
    })
    incident["hypotheses"] = stored
    incident["hypothesis_revision_history"] = history
    incident["status"] = "analysis"
    incident["updated_at"] = now()
    incident["state_version"] = int(incident.get("state_version", 1)) + 1
    incident["last_event"] = "hypotheses_revised"
    table.put_item(Item=incident)
    return {"revision_number": number, "hypotheses": stored}

def lambda_handler(event, context):
    if event.get("operation", "revise_hypotheses") != "revise_hypotheses":
        return {"statusCode": 400, "body": json.dumps({"error": "Unsupported operation", "supported_operations": ["revise_hypotheses"]})}
    incident_id = event.get("incident_id")
    if not incident_id:
        return {"statusCode": 400, "body": json.dumps({"error": "incident_id is required"})}
    try:
        result = revise(incident_id)
        return {"statusCode": 200, "body": json.dumps({"incident_id": incident_id, "model_id": MODEL, "status": "analysis", **result}, default=str)}
    except ValueError as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except ClientError as exc:
        return {"statusCode": 500, "body": json.dumps({"error": "AWS operation failed", "code": exc.response.get("Error", {}).get("Code"), "message": exc.response.get("Error", {}).get("Message")})}
    except Exception:
        logger.exception("Unexpected Hypothesis Revision Agent failure")
        return {"statusCode": 500, "body": json.dumps({"error": "Unexpected Hypothesis Revision Agent failure"})}