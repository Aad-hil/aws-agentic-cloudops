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

Your ONLY job is to review EXISTING hypotheses after independent Critic feedback.

You are NOT a hypothesis-generation agent.

STRICT RULES:
1. Never create a new hypothesis.
2. Never create a new hypothesis_id.
3. Never introduce a different causal explanation.
4. Preserve every existing hypothesis_id exactly.
5. Return exactly one result for every current hypothesis, in the same order.
6. Use only the supplied incident state, evidence, findings, hypotheses, and critic feedback.
7. Never invent telemetry, resources, metrics, logs, alarms, events, or finding IDs.
8. Missing telemetry is NOT evidence of zero activity.
9. An informational finding does NOT prove causality.
10. Remove unsupported finding references.
11. If the Critic identifies no substantive problem, use revision_action="keep" and preserve the hypothesis.
12. If the hypothesis needs correction, use revision_action="revise" while preserving its original causal scope.
13. If the hypothesis is unsupported or contradicted, use revision_action="reject". Do NOT replace it with another cause.
14. If more evidence is required, keep the existing hypothesis open or weak. Do not invent an explanation.
15. Do not perform AWS actions.
16. Do not propose remediation.
17. Confidence must be a JSON number between 0 and 1, never a string.

REVISION ACTIONS:
- keep: no substantive correction is required.
- revise: correct the existing hypothesis using supplied evidence and critic feedback.
- reject: the existing hypothesis is unsupported or contradicted.

OUTPUT FORMAT:
Return ONLY valid JSON.
Do not use markdown fences.
The response MUST contain exactly one top-level key: "hypotheses".
The value of "hypotheses" MUST be an array.

Each array item MUST contain exactly these conceptual fields:
- hypothesis_id
- revision_action
- statement
- status
- supporting_findings
- contradicting_findings
- confidence
- rationale

Allowed revision_action values:
keep, revise, reject

Allowed status values:
open, supported, weak, rejected, verified

Do not output explanations outside the JSON object.
""".strip()

    response = bedrock.converse(
        modelId=MODEL,
        system=[{"text": system}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "Revise the existing hypotheses using the supplied critic feedback. "
                            "Do not create any new hypothesis. "
                            "Return exactly one result per existing hypothesis. "
                            "Here is the incident state:\\n"
                            + json.dumps(data, default=str)
                        )
                    }
                ],
            }
        ],
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
    logger.info("Hypothesis Revision Agent raw Bedrock output: %s", raw_text)

    text = raw_text

    if text.startswith("```"):
        rows = text.splitlines()

        if rows and rows[0].strip().startswith("```"):
            rows = rows[1:]

        if rows and rows[-1].strip() == "```":
            rows = rows[:-1]

        text = "\n".join(rows).strip()

    # Handle accidental leading/trailing prose around a JSON object.
    # We do NOT silently accept arbitrary non-JSON output; this only extracts
    # the first complete JSON object so the strict validator can inspect it.
    if not text.startswith("{"):
        first_brace = text.find("{")
        last_brace = text.rfind("}")

        if first_brace >= 0 and last_brace > first_brace:
            text = text[first_brace:last_brace + 1]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Hypothesis Revision Agent invalid JSON: %s", text)
        raise ValueError(
            "Bedrock returned invalid JSON: %s" % text
        ) from exc

    if not isinstance(payload, dict):
        raise ValueError("Bedrock response must be a JSON object")

    return payload

def validate(payload, incident):
    hypotheses = payload.get("hypotheses") if isinstance(payload, dict) else None
    current = incident.get("hypotheses", [])
    if not isinstance(hypotheses, list):
        raise ValueError("Bedrock response must contain a hypotheses array")
    if [x.get("hypothesis_id") for x in hypotheses] != [x.get("hypothesis_id") for x in current]:
        raise ValueError("Revision must preserve hypothesis IDs exactly")
    valid = finding_ids(incident)
    required = {"hypothesis_id","revision_action","statement","status","supporting_findings","contradicting_findings","confidence","rationale"}
    for i, h in enumerate(hypotheses):
        missing = required - set(h)
        if missing:
            raise ValueError("hypotheses[%d] missing fields: %s" % (i, sorted(missing)))
        if h["revision_action"] not in {"keep", "revise", "reject"}:
            raise ValueError("Invalid revision_action")
        if h["revision_action"] == "reject" and h["status"] != "rejected":
            raise ValueError("Rejected revision_action must use rejected status")
        if h["revision_action"] == "keep" and h["status"] == "rejected":
            raise ValueError("Keep revision_action cannot use rejected status")
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
    response_hypotheses = []
    for h in stored:
        response_item = dict(h)
        response_item["confidence"] = float(h["confidence"])
        response_hypotheses.append(response_item)

    return {"revision_number": number, "hypotheses": response_hypotheses}

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