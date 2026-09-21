# Common Evidence Contract

## Purpose

All specialist CloudOps agents return evidence using the same top-level contract so the CloudOps Manager can aggregate independent investigations without knowing each agent's internal implementation.

## Contract

```json
{
  "application_id": "customer-analytics",
  "agent": "storage-agent",
  "investigation_type": "storage_investigation",
  "collected_at": "2026-09-21T19:07:27.876050+00:00",
  "resources_discovered": [],
  "findings": [],
  "evidence": {}
}
```

## Fields

| Field | Type | Required | Description |
|---|---|---:|---|
| application_id | string | yes | Application being investigated |
| agent | string | yes | Specialist producing the evidence |
| investigation_type | string | yes | Type of investigation performed |
| collected_at | string | yes | UTC ISO-8601 collection timestamp |
| resources_discovered | array | yes | Flat list of registry resources discovered by the agent |
| findings | array | yes | Normalized factual findings |
| evidence | object | yes | Raw/service-specific evidence |

Each item in `resources_discovered` preserves the registry resource object, for example:

```json
{
  "resource_id": "customer-analytics-data",
  "service": "dynamodb",
  "role": "application-database"
}
```

## Findings format

Each finding should be factual and traceable to evidence.

Example:

```json
{
  "finding_id": "storage-001",
  "severity": "info",
  "resource_id": "customer-analytics-data",
  "service": "dynamodb",
  "category": "table_status",
  "summary": "DynamoDB table status is ACTIVE",
  "evidence_ref": "evidence.dynamodb[0].table_status"
}
```

Allowed severity values for now:

- info
- warning
- error
- critical

The specialist agent reports facts. It does not make root-cause or remediation decisions.

## Agent names

Current specialists:

- `observability-agent`
- `storage-agent`

Future agents should use the same contract.

## Design rule

The contract separates:

- **findings** — normalized facts useful to the orchestrator
- **evidence** — detailed raw observations returned by AWS tools

This allows the Manager, Root Cause Agent, Critic Agent, and Remediation Planner to consume evidence consistently without depending on service-specific response shapes.

## Example

```json
{
  "application_id": "customer-analytics",
  "agent": "storage-agent",
  "investigation_type": "storage_investigation",
  "collected_at": "2026-09-21T19:07:27.876050+00:00",
  "resources_discovered": [
    {
      "resource_id": "customer-analytics-upload-aadhil-poc",
      "service": "s3",
      "role": "application-storage"
    },
    {
      "resource_id": "customer-analytics-data",
      "service": "dynamodb",
      "role": "application-database"
    },
    {
      "resource_id": "customer-analytics-s3-upload",
      "service": "eventbridge",
      "role": "event-routing"
    }
  ],
  "findings": [
    {
      "finding_id": "storage-001",
      "severity": "info",
      "resource_id": "customer-analytics-data",
      "service": "dynamodb",
      "category": "table_status",
      "summary": "DynamoDB table status is ACTIVE",
      "evidence_ref": "evidence.dynamodb[0].table_status"
    }
  ],
  "evidence": {
    "s3": [],
    "dynamodb": [],
    "eventbridge": []
  }
}
```
