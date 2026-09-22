# Common Evidence Contract

All specialist CloudOps agents return evidence using the same top-level contract. The contract distinguishes observed facts, telemetry gaps, absence-only observations, configuration state, access checks, causal candidates, and contradictory facts.

## Top-level Contract

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

## Finding Contract

Every finding should contain:

```json
{
  "finding_id": "example-finding-id",
  "severity": "info",
  "finding_type": "telemetry_observation",
  "evidence_semantics": "observed_fact",
  "summary": "Example factual observation.",
  "evidence_ref": "evidence.example"
}
```

Required: `finding_id`, `severity`, `finding_type`, `evidence_semantics`, `summary`.

Allowed severity values: `info`, `warning`, `error`, `critical`.

## Evidence Semantics

### observed_fact
A directly observed factual condition.

### absence_only
A query returned no observed activity, such as zero CloudWatch log events. This does not prove that the underlying activity did not occur and MUST NOT be used as causal evidence.

### telemetry_gap
A telemetry query returned no datapoints or otherwise could not establish underlying activity. It is not numeric zero and MUST NOT support or contradict a causal hypothesis.

### configuration_state
A configured or administrative state such as EventBridge ENABLED. Configuration state does not prove runtime behavior.

### access_observation
The result of an explicit access or permission check. It applies only to the operation actually tested and does not prove every application operation succeeds.

### causal_candidate
A concrete observed failure that can reasonably be considered causal evidence, such as an application upload returning AccessDenied. It does not automatically establish root cause.

### contradictory_fact
An observed fact that directly conflicts with a hypothesis. Missing evidence is never contradictory evidence.

## Semantic Rules

The following inferences are invalid:

```text
no CloudWatch logs -> Lambda was not invoked
no invocation datapoints -> Lambda had zero invocations
EventBridge no_data -> EventBridge did not trigger
EventBridge ENABLED -> EventBridge successfully delivered events
S3 accessible to investigation role -> application uploads cannot fail
```

## Finding IDs

Finding IDs should describe the observation, not an inferred conclusion.

Good:
```text
lambda-api-invocations-no-data
lambda-api-logs-no-events
eventbridge-upload-enabled
eventbridge-upload-pattern-validation
s3-upload-access-denied
```

Avoid conclusion-based IDs such as `lambda-api-not-invoked`, `eventbridge-broken`, or `s3-permission-root-cause` unless the underlying investigation actually established those facts.

## Specialist Responsibility

Specialist agents discover registered resources, collect service telemetry, report factual findings, assign evidence semantics, preserve evidence gaps, and avoid unsupported causal conclusions.

Specialists do not select root cause or perform remediation.

## Manager Responsibility

The CloudOps Manager validates finding references and prevents absence-only, telemetry-gap, configuration-state, and access-observation findings from being treated as causal evidence.

## Reasoning Layer

The reasoning layer may generate multiple hypotheses and identify evidence gaps. It MUST NOT treat missing telemetry as zero, treat absence as causation, treat configuration as runtime behavior, invent telemetry failures, invent finding IDs, or claim root cause without sufficient evidence.

## Root Cause Flow

```text
Specialist Evidence
        |
        v
Hypotheses
        |
        v
Critic
        |
        v
Hypothesis Revision
        |
        v
Root Cause Assessment
```

Root cause remains unsupported when the evidence does not establish a meaningful causal connection.
