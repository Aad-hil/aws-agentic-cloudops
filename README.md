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

- [ ] Registry table
- [ ] Application resource metadata
- [ ] Dependency graph
- [ ] Automated resource discovery

### Future phases

- [ ] CloudOps Manager
- [ ] Observability Agent
- [ ] Storage Agent
- [ ] Infrastructure Agent
- [ ] Knowledge / Architecture Agent
- [ ] Remediation Agent
- [ ] Bedrock Knowledge Base / RAG
- [ ] Shared incident state
- [ ] Agent collaboration and hypothesis validation
- [ ] Human approval workflow
- [ ] Remediation verification
- [ ] Incident memory

## Engineering principles

- Application-scoped operations
- Least-privilege IAM
- Evidence before conclusions
- Specialized agents instead of one general agent
- Human approval for high-impact remediation
- Verification after remediation
- AWS resources reproducible through infrastructure as code
- GitHub repository as the source of truth

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

## Status

POC in active development.

