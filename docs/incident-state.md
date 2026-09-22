# Incident State

## Purpose

The Incident State store is the shared working memory for the CloudOps team.

It represents the current state of one incident and allows the CloudOps Manager and specialist agents to contribute findings without turning the system into a collection of isolated agent calls.

DynamoDB table:

`customer-analytics-incidents`

## Design goals

- Application-scoped incidents
- Persistent shared investigation state
- Explicit lifecycle/status
- Specialist delegation tracking
- Evidence and findings aggregation
- Hypothesis tracking
- Remediation and approval state
- Verification state
- Future incident-memory support
- Simple enough for the POC
- Avoid storing unbounded raw telemetry in DynamoDB

## Primary key

| Attribute | Type | Purpose |
|---|---|---|
| `incident_id` | String | Partition key; unique incident identifier |

## Global secondary index

**Index:** `application_id-created_at-index`

| Attribute | Type |
|---|---|
| `application_id` | String |
| `created_at` | String |

Purpose: retrieve incidents for a specific application in creation-time order.

## Incident lifecycle

The initial state machine is:

```text
created
   ↓
planning
   ↓
investigating
   ↓
analysis
   ↓
awaiting_approval
   ↓
remediating
   ↓
verifying
   ↓
resolved
```

Failure/termination paths may use:

- `failed`
- `cancelled`

The Manager is responsible for normal lifecycle transitions. Specialist agents should primarily contribute investigation results rather than independently changing the overall incident lifecycle.

## Initial item schema

```json
{
  "incident_id": "INC-000001",
  "application_id": "customer-analytics",
  "environment": "poc",
  "region": "us-east-1",
  "status": "created",
  "severity": "medium",
  "reported_symptoms": [
    "S3 uploads are failing",
    "CloudWatch is showing errors"
  ],
  "created_at": "2026-09-22T07:00:00+00:00",
  "updated_at": "2026-09-22T07:00:00+00:00",
  "state_version": 1,

  "application_context": {
    "name": "Customer Analytics Platform",
    "resource_count": 6,
    "dependency_count": 6
  },

  "investigation_plan": [],

  "delegations": [],

  "agent_findings": [],

  "evidence": [],

  "hypotheses": [],

  "open_questions": [],

  "actions": [],

  "decision": null,

  "approval": {
    "required": false,
    "status": "not_required"
  },

  "remediation": null,

  "verification": null,

  "last_event": "incident_created"
}
```

## Investigation plan item

Each planned task should contain:

```json
{
  "task_id": "TASK-001",
  "agent": "observability-agent",
  "operation": "investigate_logs",
  "status": "pending",
  "created_at": "..."
}
```

Allowed task states:

- `pending`
- `running`
- `completed`
- `failed`
- `skipped`

## Delegation item

A delegation records an actual request made to a specialist:

```json
{
  "delegation_id": "DEL-001",
  "task_id": "TASK-001",
  "agent": "observability-agent",
  "operation": "investigate_logs",
  "requested_at": "...",
  "completed_at": "...",
  "status": "completed"
}
```

## Agent finding

Agent findings use the Common Evidence Contract's normalized finding shape.

Example:

```json
{
  "finding_id": "metrics-customer-analytics-api-errors",
  "agent": "observability-agent",
  "severity": "error",
  "resource_id": "customer-analytics-api",
  "service": "lambda",
  "category": "lambda_errors",
  "summary": "Lambda reported 1 error",
  "evidence_ref": "evidence.functions"
}
```

## Evidence

The incident record should store compact evidence needed for coordination and reasoning.

Large raw telemetry should not grow the incident item without bounds. Later, raw investigation outputs can be stored in S3 and referenced from the incident.

Example:

```json
{
  "evidence_id": "EVD-001",
  "agent": "observability-agent",
  "investigation_type": "get_metrics",
  "collected_at": "...",
  "source": "cloudwatch",
  "summary": "API Lambda reported 1 error across 3 invocations",
  "artifact_uri": null
}
```

## Hypothesis

```json
{
  "hypothesis_id": "H-001",
  "statement": "The API Lambda is experiencing an application-level failure",
  "status": "open",
  "supporting_findings": [],
  "contradicting_findings": [],
  "confidence": null
}
```

Allowed hypothesis states:

- `open`
- `supported`
- `weak`
- `rejected`
- `verified`

Confidence is intentionally nullable until the reasoning phase is implemented.

## Decision

The final decision is kept separate from individual hypotheses:

```json
{
  "type": "root_cause_assessment",
  "statement": null,
  "supporting_evidence": [],
  "uncertainty": [],
  "decided_at": null
}
```

The system must preserve evidence and uncertainty instead of replacing them with an unsupported conclusion.

## Approval

High-impact remediation uses:

```json
{
  "required": true,
  "status": "pending",
  "requested_at": "...",
  "requested_action": "...",
  "risk": "medium",
  "rollback": "...",
  "approved_at": null
}
```

Allowed approval states:

- `not_required`
- `pending`
- `approved`
- `rejected`

## Design constraint

DynamoDB is the shared incident state store, not the long-term raw telemetry store.

The POC should keep the incident item compact. As evidence becomes larger, store artifacts in S3 and keep references in the incident state.

## Current implementation scope

For the first implementation, create the DynamoDB table and validate:

1. An incident can be created.
2. The incident can be retrieved by `incident_id`.
3. Incidents can be queried by `application_id`.
4. State can be updated while preserving `state_version`.
5. Specialist findings can later be appended by the CloudOps Manager.

The CloudOps Manager will be built after this storage layer is validated.
