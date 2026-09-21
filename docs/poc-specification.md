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

### Safety model

High-impact or destructive remediation actions require explicit human approval. Agents should present evidence, uncertainty, proposed action, risk, and rollback information before execution.
