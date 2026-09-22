# AWS Agentic CloudOps

Project-aware multi-agent AI CloudOps POC for troubleshooting and operating a single AWS application.

## Project goal

Build a small collaborative CloudOps team using Amazon Bedrock and AWS-native services:

User → Manager → Specialized Agents → Evidence → Hypothesis Validation → Human Approval → Remediation → Verification → Incident Memory

## Current target application

**Customer Analytics Platform**

- Application ID: `customer-analytics`
- Environment: `poc`
- Primary region: `us-east-1`

### Current AWS architecture

```text
API Gateway
    ↓
API Lambda
    ├──→ S3
    └──→ DynamoDB

S3
    ↓ Object Created
EventBridge
    ↓
Worker Lambda
    ↓
DynamoDB

CloudWatch
    ↓
Application telemetry
```

## Current implementation status

### Phase 1 — Target Application

- [x] S3 upload bucket
- [x] DynamoDB application data table
- [x] API Lambda
- [x] API Gateway `GET /health`
- [x] Worker Lambda
- [x] S3 → EventBridge
- [x] EventBridge → Worker Lambda
- [x] Worker Lambda → DynamoDB
- [x] CloudWatch logging

### Phase 2 — Application Registry

- [x] Registry table
- [x] Application resource metadata
- [x] Dependency graph
- [x] Registry API
- [x] Application-scoped resource discovery

### Phase 3 — Specialist Investigation Agents

#### Observability Agent — COMPLETE

- [x] Application Registry integration
- [x] Dynamic Lambda discovery
- [x] CloudWatch Logs investigation
- [x] Recent-log pagination and newest-event selection
- [x] CloudWatch Alarm investigation
- [x] Lambda metrics investigation
- [x] Structured findings
- [x] Common Evidence Contract
- [x] Incident failure test successfully detects Lambda errors

#### Storage Agent — COMPLETE

- [x] Application Registry integration
- [x] Dynamic S3 resource discovery
- [x] S3 bucket investigation
- [x] Object/activity investigation
- [x] DynamoDB resource investigation
- [x] EventBridge resource/rule investigation
- [x] Structured findings
- [x] Common Evidence Contract
- [x] Tested against the Customer Analytics application resources

### Phase 4 — Incident Orchestration — IN PROGRESS

- [x] Shared incident state DynamoDB table
- [x] Incident schema
- [x] CloudOps Manager v1
- [x] Incident creation
- [x] Investigation planning
- [x] Specialist delegation framework
- [x] Complete evidence aggregation across all specialists
- [x] Incident lifecycle/state transitions
- [x] Manager → Observability Agent delegation
- [x] Manager → Storage Agent delegation
- [x] Investigation plan task status persisted in DynamoDB
- [x] Four specialist tasks completed in a clean end-to-end run
- [x] Four agent evidence records persisted
- [x] Storage Agent S3 + DynamoDB + EventBridge evidence aggregated

Current validation checkpoint:
- Incident `INC-F70EC79C` is persisted in DynamoDB.
- Observability `TASK-001`, `TASK-002`, and `TASK-003` completed successfully.
- Three Observability findings and three compact evidence records were persisted.
- Storage `TASK-004` failed because the Manager requested `investigate_storage`, while the deployed Storage Agent accepts `investigate_s3`, `investigate_dynamodb`, `investigate_eventbridge`, and `investigate_all`.
- The Manager has been corrected to use `investigate_all`; the next AWS test must be run after deploying that change.

### Phase 5 — Multi-Agent Reasoning

- [ ] Agent-to-agent communication
- [ ] Evidence synthesis
- [ ] Competing hypotheses
- [ ] Hypothesis validation
- [ ] Critic / challenge agent
- [ ] Root-cause assessment
- [ ] Confidence and uncertainty representation

### Phase 6 — Additional Specialists

- [ ] Infrastructure Agent
- [ ] Knowledge / Architecture Agent
- [ ] Bedrock Knowledge Base / RAG

EC2/VPC infrastructure will be introduced when the Infrastructure Agent needs realistic infrastructure investigation scenarios.

### Phase 7 — Remediation and Safety

- [ ] Remediation planning
- [ ] Human approval workflow
- [ ] Remediation Agent
- [ ] Safe execution tools
- [ ] Rollback information
- [ ] Post-remediation verification

### Phase 8 — Incident Memory and Evaluation

- [ ] Incident memory
- [ ] Historical incident retrieval
- [ ] Evaluation dataset
- [ ] End-to-end evaluation
- [ ] Operational dashboard

## Engineering principles

- Application-scoped operations
- Least-privilege IAM
- Evidence before conclusions
- Specialized agents instead of one general agent
- Common Evidence Contract between specialist agents and the Manager
- Human approval for high-impact remediation
- Verification after remediation
- AWS resources reproducible through infrastructure as code
- GitHub repository as the source of truth
- AWS is the execution environment

## Repository structure

```text
aws-agentic-cloudops/
├── application/
├── agents/
├── docs/
├── infrastructure/
├── knowledge/
├── registry/
├── tests/
└── tools/
```

## Security

Do not commit:

- AWS credentials
- API keys
- Secrets
- Passwords
- Private keys
- Employer-confidential information

Use environment variables, IAM roles, AWS Secrets Manager, or other appropriate secret-management mechanisms instead.

## Current checkpoint

The target application, Application Registry, Observability Agent, Storage Agent, Common Evidence Contract, Incident State table, and CloudOps Manager v1 are implemented.

The Manager has been validated in AWS through a clean end-to-end incident investigation. All four specialist tasks completed, findings were persisted from both Observability and Storage Agents, and four compact evidence records were aggregated into shared incident state. Phase 4 is complete. The next phase is the reasoning layer: Bedrock-assisted hypothesis generation, evidence analysis, and hypothesis validation.

## Status

POC in active development.
