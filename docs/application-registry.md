# Application Registry

The Application Registry is the source of application-specific infrastructure context used by the future CloudOps Manager and specialized agents.

## Purpose

The registry answers:

> Which AWS resources belong to this application, and how are they related?

It keeps application identity separate from application runtime data.

## Current application

- Application ID: `customer-analytics`
- Name: Customer Analytics Platform
- Environment: `poc`
- Region: `us-east-1`

## Current resources

| Service | Resource | Role |
|---|---|---|
| S3 | `customer-analytics-upload-aadhil-poc` | Application storage |
| Lambda | `customer-analytics-api` | API |
| Lambda | `customer-analytics-worker` | Background worker |
| DynamoDB | `customer-analytics-data` | Application database |
| API Gateway | `customer-analytics-api` | API entrypoint |
| EventBridge | `customer-analytics-s3-upload` | Event routing |

## Current dependency graph

```text
API Gateway
    |
    v
API Lambda
    |-----------------> S3
    |
    +-----------------> DynamoDB

S3
 |
 | Object Created
 v
EventBridge Rule
 |
 v
Worker Lambda
 |
 v
DynamoDB
```

## Ownership boundary

Resources are intended to be associated with the application through:

```text
Application=customer-analytics
Environment=poc
ManagedBy=cloudops-ai
```

The registry is initially seeded manually. Automated discovery will be added later using AWS APIs and resource tags.

## Future registry API

The registry will eventually expose application context to agents through operations such as:

- `get_application()`
- `get_application_resources()`
- `get_application_dependencies()`
- `get_resource()`

This allows agents to remain application-aware without embedding infrastructure details into their prompts.
