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

### Phase 4 — Incident Orchestration — COMPLETE

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

Validation checkpoint:
- Clean incident `INC-AF76D3C6` completed the full four-task investigation.
- Observability `TASK-001`, `TASK-002`, and `TASK-003` completed successfully.
- Storage `TASK-004` completed successfully with S3, DynamoDB, and EventBridge evidence.
- Four specialist evidence records were persisted in shared incident state.
- Phase 4 investigation and evidence aggregation are complete.

### Phase 5 — Multi-Agent Reasoning — IN PROGRESS

- [x] Reasoning contract
- [x] Deterministic reasoning-input builder
- [x] Bedrock Nova 2 Lite hypothesis generation
- [x] JSON parsing and hypothesis validation
- [x] Finding-reference validation
- [x] Competing hypotheses
- [x] Hypothesis persistence
- [ ] Agent-to-agent critique handoff
- [x] Critic Agent contract and initial implementation
- [ ] Critic Agent AWS deployment and validation
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

The Manager has been validated in AWS through a clean end-to-end incident investigation. All four specialist tasks completed, findings were persisted from both Observability and Storage Agents, and four compact evidence records were aggregated into shared incident state. Phase 4 is complete.

Phase 5A is also validated: Nova 2 Lite generates competing hypotheses through an inference profile, the Manager parses and validates the JSON, checks finding references, and persists the hypotheses. The validated incident is use the AWS incident ID shown by the test environment as the source of truth.

Phase 5B has started with the independent Critic Agent. The next step is deploying and validating it against `INC-AF76D3C6`, especially the incorrect inference that zero returned metric datapoints means zero Lambda invocations.

## Status

POC in active development.


Phase 5A hypothesis generation is implemented and validated. Phase 5B starts with `docs/critic-contract.md` and `agents/critic/lambda_function.py`. Next: deploy the Critic Agent, run it against the generated hypotheses, and inspect whether it correctly challenges unsupported evidence interpretations.
