import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

INCIDENTS_TABLE_NAME = os.getenv("INCIDENTS_TABLE_NAME", "customer-analytics-incidents")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")

dynamodb = boto3.resource("dynamodb")
incidents_table = dynamodb.Table(INCIDENTS_TABLE_NAME)
bedrock_runtime = boto3.client("bedrock-runtime")
VALID_VERDICTS = {"supported", "unsupported", "needs_more_evidence"}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_incident(incident_id):
    result = incidents_table.get_item(Key={"incident_id": incident_id})
    incident = result.get("Item")
    if not incident:
        raise ValueError(f"Incident not found: {incident_id}")
    return incident

def collect_finding_ids(incident):
    ids = set()
    for agent_result in incident.get("agent_findings", []):
        for finding in agent_result.get("findings", []):
            if finding.get("finding_id"):
                ids.add(finding["finding_id"])
    return ids

def build_critic_input(incident):
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
        "open_questions": incident.get("open_questions", []),
    }

def invoke_bedrock(critic_input, valid_finding_ids):
    system_prompt = """
You are the Critic Agent in an AWS CloudOps multi-agent system.
Challenge each supplied hypothesis against the supplied evidence.
Check whether cited findings actually support or contradict the hypothesis.
Detect unsupported claims and the mistake of treating missing telemetry as zero.
Identify missing evidence needed to validate the hypothesis.
Do not invent telemetry, resources, metrics, logs, alarms, events, or finding IDs.
Do not perform AWS actions or propose destructive remediation.
Return ONLY valid JSON with a top-level critiques array.
Each critique must contain: hypothesis_id, verdict, issues, valid_supporting_findings,
valid_contradicting_findings, missing_evidence, confidence, rationale.
verdict must be supported, unsupported, or needs_more_evidence.
confidence must be between 0 and 1.
IMPORTANT: valid_supporting_findings and valid_contradicting_findings are strict references to finding IDs only.
Use ONLY values from the explicit FINDING ID ALLOWLIST below.
Never use evidence IDs, evidence summaries, task IDs, delegation IDs, operation names,
or phrases such as "get_alarms completed" as finding references.
If no finding ID directly supports or contradicts the hypothesis, return an empty array.
Missing telemetry is not contradictory evidence and is not proof of zero.
A configured/enabled resource does not prove runtime delivery or success.
An accessible resource does not prove the application operation succeeds.

""".strip()
    user_prompt = (
        "Critique the supplied hypotheses using ONLY the incident context and specialist evidence. "
        "Do not create new hypotheses. Do not rank hypotheses. "
        "Use only the exact finding IDs in this allowlist for finding references.\n\n"
        "FINDING ID ALLOWLIST:\n"
        + json.dumps(sorted(valid_finding_ids))
        + "\n\nINCIDENT CONTEXT:\n"
        + json.dumps(critic_input, default=str)
    )

    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={"maxTokens": 1800, "temperature": 0.0},
    )
    content = response.get("output", {}).get("message", {}).get("content", [])
    text_parts = [block["text"] for block in content if "text" in block]
    if not text_parts:
        raise ValueError("Bedrock returned no text content")
    text = "".join(text_parts).strip()
    if text.startswith("```"):
        parts = text.splitlines()
        text = "\n".join(parts[1:-1] if parts and parts[-1].strip() == "```" else parts[1:]).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Bedrock returned invalid JSON: {text}") from exc

def validate_critiques(payload, incident):
    if not isinstance(payload, dict) or not isinstance(payload.get("critiques"), list):
        raise ValueError("Critic response must contain a critiques array")
    hypothesis_ids = {h.get("hypothesis_id") for h in incident.get("hypotheses", [])}
    finding_ids = collect_finding_ids(incident)
    required = {"hypothesis_id", "verdict", "issues", "valid_supporting_findings", "valid_contradicting_findings", "missing_evidence", "confidence", "rationale"}
    for i, critique in enumerate(payload["critiques"]):
        missing = required - set(critique)
        if missing:
            raise ValueError(f"critiques[{i}] missing fields: {sorted(missing)}")
        if critique["hypothesis_id"] not in hypothesis_ids:
            raise ValueError(f"Unknown hypothesis_id: {critique['hypothesis_id']}")
        if critique["verdict"] not in VALID_VERDICTS:
            raise ValueError(f"Invalid verdict: {critique['verdict']}")
        confidence = critique["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError(f"Invalid confidence for {critique['hypothesis_id']}")
        for field in ("issues", "valid_supporting_findings", "valid_contradicting_findings", "missing_evidence"):
            if not isinstance(critique[field], list):
                raise ValueError(f"{field} must be an array")
        for field in ("valid_supporting_findings", "valid_contradicting_findings"):
            unknown = [x for x in critique[field] if x not in finding_ids]
            if unknown:
                raise ValueError(f"Unknown finding IDs: {unknown}")
    return payload["critiques"]

def critique_hypotheses(incident_id):
    incident = get_incident(incident_id)
    if not incident.get("hypotheses"):
        raise ValueError("No hypotheses exist. Generate hypotheses first.")
    valid_finding_ids = collect_finding_ids(incident)
    output = invoke_bedrock(build_critic_input(incident), valid_finding_ids)
    critiques = validate_critiques(output, incident)
    stored = []
    for critique in critiques:
        item = dict(critique)
        item["confidence"] = Decimal(str(critique["confidence"]))
        stored.append(item)
    incident["hypothesis_critiques"] = stored
    incident["status"] = "analysis"
    incident["updated_at"] = now_iso()
    incident["state_version"] = int(incident.get("state_version", 1)) + 1
    incident["last_event"] = "hypotheses_critique_completed"
    incidents_table.put_item(Item=incident)
    return stored

def lambda_handler(event, context):
    if event.get("operation", "critique_hypotheses") != "critique_hypotheses":
        return {"statusCode": 400, "body": json.dumps({"error": "Unsupported operation", "supported_operations": ["critique_hypotheses"]})}
    incident_id = event.get("incident_id")
    if not incident_id:
        return {"statusCode": 400, "body": json.dumps({"error": "incident_id is required"})}
    try:
        critiques = critique_hypotheses(incident_id)
        return {"statusCode": 200, "body": json.dumps({"incident_id": incident_id, "model_id": BEDROCK_MODEL_ID, "status": "analysis", "critiques": critiques}, default=str)}
    except ValueError as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except ClientError as exc:
        return {"statusCode": 500, "body": json.dumps({"error": "AWS operation failed", "code": exc.response.get("Error", {}).get("Code"), "message": exc.response.get("Error", {}).get("Message")})}
    except Exception as exc:
        return {"statusCode": 500, "body": json.dumps({"error": "Unexpected Critic Agent failure", "message": str(exc)})}
