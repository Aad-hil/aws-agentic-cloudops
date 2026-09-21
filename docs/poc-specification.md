# AWS Project-Aware Multi-Agent CloudOps Team

## POC Specification

### Objective

Build a project-aware multi-agent AI CloudOps team for a single AWS-hosted application.

The system should demonstrate:

- Application awareness
- Resource and dependency awareness
- Multi-agent planning and delegation
- Role-specific AWS tools
- Shared incident state
- Evidence-based investigation
- Hypothesis validation
- RAG-based operational knowledge
- Human-approved remediation
- Post-remediation verification
- Incident memory

### Investigation lifecycle

User Report
→ Incident Creation
→ Application Identification
→ Application Context
→ Investigation Planning
→ Task Decomposition
→ Specialist Investigation
→ Evidence Collection
→ Agent Discussion
→ Hypothesis Challenge
→ Root-Cause Assessment
→ Remediation Plan
→ Human Approval
→ Remediation
→ Verification
→ Incident Resolution
→ Incident Memory

### Initial agent team

1. CloudOps Manager
2. Observability Agent
3. Storage / Service Agent
4. Infrastructure Agent
5. Knowledge / Architecture Agent
6. Remediation Agent

### Target application

Customer Analytics Platform

Application ID: `customer-analytics`

Environment: `poc`

Region: `us-east-1`

### Initial AWS services

- API Gateway
- AWS Lambda
- Amazon S3
- Amazon DynamoDB
- Amazon EventBridge
- Amazon CloudWatch

EC2/VPC infrastructure will be introduced later when the Infrastructure Agent needs realistic infrastructure investigation scenarios.

## Implementation phases

### Phase 1 — Target Application — COMPLETE

The POC application currently contains:

- S3 upload bucket
- DynamoDB application data table
- API Lambda
- API Gateway `GET /health`
- Worker Lambda
- S3 → EventBridge
- EventBridge → Worker Lambda
- Worker Lambda → DynamoDB
- CloudWatch logging

### Phase 2 — Application Registry — COMPLETE

The application boundary is represented by an Application Registry stored in DynamoDB.

Registry table:

`customer-analytics-registry`

Registry API:

`customer-analytics-registry-api`

Current operation:

`get_application(application_id)`

The Registry API is intentionally read-only and has only `dynamodb:GetItem` permission on the registry table.

The registry currently contains application resources and dependency metadata for the Customer Analytics Platform.

### Phase 3 — Specialist Investigation Agents — COMPLETE

#### Observability Agent

Lambda:

`customer-analytics-observability-agent`

Responsibilities:

- Discover Lambda resources from the Application Registry
- Investigate CloudWatch Logs
- Investigate CloudWatch Alarms
- Investigate Lambda metrics
- Produce normalized findings and detailed evidence

The agent uses the Common Evidence Contract and has been validated against a simulated Lambda failure.

#### Storage Agent

Lambda:

`customer-analytics-storage-agent`

Responsibilities:

- Discover storage and event-routing resources from the Application Registry
- Investigate S3 resources and object activity
- Investigate DynamoDB application data resources
- Investigate EventBridge rules and routing
- Produce normalized findings and detailed evidence

The agent uses the Common Evidence Contract and has been tested against the Customer Analytics application.

### Phase 4 — Incident Orchestration — NEXT

Build the persistent incident state layer and the CloudOps Manager.

Initial components:

- `customer-analytics-incidents` DynamoDB table
- Incident schema
- CloudOps Manager
- Incident creation
- Investigation planning
- Specialist delegation
- Evidence aggregation
- Incident status transitions

The first orchestration version should be deterministic and explicit before introducing LLM-driven planning into every step.

### Phase 5 — Multi-Agent Reasoning

Add:

- Agent-to-agent communication
- Evidence synthesis
- Competing hypotheses
- Hypothesis validation
- Critic/challenge behavior
- Root-cause assessment
- Explicit uncertainty and confidence representation

### Phase 6 — Additional Investigation Capabilities

Add the Infrastructure Agent and Knowledge / Architecture Agent.

Introduce EC2/VPC resources when they are required to create realistic infrastructure investigation scenarios.

Add Bedrock Knowledge Base / RAG for architecture and operational knowledge.

### Phase 7 — Remediation and Safety

Add:

- Remediation planning
- Human approval
- Remediation Agent
- Safe execution tools
- Rollback information
- Post-remediation verification

High-impact or destructive remediation actions require explicit human approval. Agents should present evidence, uncertainty, proposed action, risk, and rollback information before execution.

### Phase 8 — Incident Memory and Evaluation

Add:

- Incident memory
- Historical incident retrieval
- Evaluation dataset
- End-to-end evaluation
- Operational dashboard

### Common Evidence Contract

Specialist agents return a normalized envelope:

```json
{
  "application_id": "customer-analytics",
  "agent": "observability-agent",
  "investigation_type": "investigate_logs",
  "collected_at": "...",
  "resources_discovered": [],
  "findings": [],
  "evidence": {}
}
```

The contract separates normalized findings from detailed service-specific evidence so the CloudOps Manager can combine evidence from independent specialists without requiring identical internal implementations.

### Safety model

High-impact or destructive remediation actions require explicit human approval. Agents should present evidence, uncertainty, proposed action, risk, and rollback information before execution.
