# CloudOps Manager v1

## Purpose

The CloudOps Manager is the orchestration entry point for an incident.

This first implementation is intentionally deterministic. It does not use Bedrock yet.

Flow:

```text
Incident request
      |
      v
CloudOps Manager
      |
      +--> Application Registry
      |
      +--> Create incident state
      |
      +--> Build investigation plan
      |
      v
DynamoDB: customer-analytics-incidents
```

## Lambda

Recommended function name:

`customer-analytics-cloudops-manager`

Runtime:

- Python 3.14
- Handler: `lambda_function.lambda_handler`

Environment variables:

| Variable | Value |
|---|---|
| `INCIDENTS_TABLE_NAME` | `customer-analytics-incidents` |
| `REGISTRY_FUNCTION_NAME` | `customer-analytics-registry-api` |
| `DEFAULT_ENVIRONMENT` | `poc` |
| `DEFAULT_REGION` | `us-east-1` |

## v1 responsibilities

1. Validate an incident request.
2. Query the Application Registry.
3. Create a unique incident ID.
4. Copy application context into the incident.
5. Create an initial investigation plan.
6. Persist the incident in DynamoDB.
7. Return the complete incident state.

## v1 investigation plan

The initial deterministic plan delegates investigation to existing specialists:

- Observability Agent: `investigate_logs`
- Observability Agent: `get_metrics`
- Observability Agent: `get_alarms` when CloudWatch is mentioned
- Storage Agent: `investigate_all` (runs the S3, DynamoDB, and EventBridge investigations within the Storage Agent)

The Manager does not perform those investigations itself.

## Test event

```json
{
  "operation": "create_incident",
  "application_id": "customer-analytics",
  "reported_symptoms": [
    "S3 uploads are failing",
    "CloudWatch is showing errors"
  ],
  "severity": "medium"
}
```

Expected:

- HTTP-style `statusCode`: `201`
- New incident ID such as `INC-A1B2C3D4`
- Application context from the registry
- Status: `planning`
- Four investigation tasks
- No specialist findings yet

## IAM permissions

The Manager needs:

- `lambda:InvokeFunction` on `customer-analytics-registry-api`
- `dynamodb:PutItem` on `customer-analytics-incidents`
- CloudWatch Logs permissions required by the Lambda execution role

Later phases will add:

- `dynamodb:GetItem`
- `dynamodb:UpdateItem`
- specialist Lambda invocation permissions
- Bedrock permissions

## Specialist delegation v1

The Manager now supports `investigate_incident`.

It reads the incident from DynamoDB and delegates pending plan tasks to the existing specialist Lambdas:

- Observability: `investigate_logs`, `get_metrics`, `get_alarms`
- Storage: `investigate_all`

Each specialist receives the incident context and returns its evidence contract. The Manager records delegation status, agent findings, compact evidence, and task status back into the shared incident item.

The Manager does not perform specialist AWS investigations itself.

### Investigation test event

```json
{
  "operation": "investigate_incident",
  "incident_id": "INC-XXXXXXXX"
}
```

Expected lifecycle:

```text
planning
   ↓
investigating
   ↓
specialist delegation
   ↓
agent findings + evidence
   ↓
analysis
```

## Next phase

After specialist delegation works, the Manager will be extended to:

```text
Manager
  |
  +--> create plan
  |
  +--> delegate to Observability Agent
  |
  +--> delegate to Storage Agent
  |
  +--> collect evidence
  |
  +--> update shared incident state
```

Bedrock reasoning comes after this deterministic orchestration path is proven.


## AWS validation checkpoint — 2026-09-22

The incident `INC-F70EC79C` was persisted successfully and the Manager completed all three Observability delegations:

- `TASK-001` → `investigate_logs` → completed
- `TASK-002` → `get_metrics` → completed
- `TASK-003` → `get_alarms` → completed

The same DynamoDB item also persisted three Observability agent findings and three compact evidence records.

The Storage delegation exposed an integration mismatch: the Manager originally requested `investigate_storage`, while the deployed Storage Agent accepts `investigate_s3`, `investigate_dynamodb`, `investigate_eventbridge`, and `investigate_all`. This caused `TASK-004` to fail with HTTP-style status 400. The Manager has now been corrected to request `investigate_all`.

A new incident investigation must be run after deploying the updated Manager to validate Storage Agent findings and evidence end-to-end.
