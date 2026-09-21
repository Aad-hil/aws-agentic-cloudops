# Current Architecture

## Application

The POC currently implements an event-driven Customer Analytics Platform.

```text
                     API Gateway
                          |
                          v
                    API Lambda
                    /         \
                   v           v
                  S3        DynamoDB

                  S3
                  |
           Object Created
                  |
                  v
             EventBridge
                  |
                  v
              Worker Lambda
                  |
                  v
              DynamoDB

              CloudWatch
                  |
                  v
             Application Logs
```

## Application boundary

Resources are scoped to:

- Application: `customer-analytics`
- Environment: `poc`
- Region: `us-east-1`

Recommended resource tags:

```text
Application=customer-analytics
Environment=poc
ManagedBy=cloudops-ai
```

## Implemented application flow

1. A client invokes `GET /health` through API Gateway.
2. API Gateway invokes `customer-analytics-api`.
3. S3 object creation events are sent to EventBridge.
4. An EventBridge rule filters events for the application S3 bucket.
5. EventBridge invokes `customer-analytics-worker`.
6. The worker records the upload event in `customer-analytics-data`.
7. Lambda logs provide CloudWatch telemetry.

## CloudOps investigation architecture

The Application Registry provides the application boundary to specialist agents.

```text
                    Application Registry
                            |
              +-------------+-------------+
              |                           |
              v                           v
     Observability Agent           Storage Agent
              |                           |
       +------+------+              +-----+------+
       |      |      |              |     |      |
      Logs  Alarms Metrics          S3  DynamoDB EventBridge
       |      |      |              |     |      |
       +------+------+              +-----+------+
              |                           |
              +-------------+-------------+
                            |
                            v
                    Common Evidence
                       Contract
                            |
                            v
                    CloudOps Manager
                    (next phase)
```

## Current implementation boundary

Implemented:

- Target application
- Application Registry
- Observability Agent
- Storage Agent
- Common Evidence Contract

Next:

- Shared incident state
- CloudOps Manager
- Specialist delegation
- Evidence aggregation

Later:

- Multi-agent hypothesis validation
- Infrastructure and Knowledge agents
- RAG
- Human-approved remediation
- Verification
- Incident memory

## Design direction

GitHub is the source of truth for application code, documentation, and infrastructure definitions. AWS is the execution environment.

Infrastructure will be progressively codified with SAM/CloudFormation after the initial console-first learning pass.
