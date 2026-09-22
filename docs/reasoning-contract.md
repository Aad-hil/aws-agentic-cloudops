# Reasoning Contract

## Purpose

Phase 5 adds reasoning after deterministic specialist investigation.

The reasoning layer must consume persisted incident facts and produce structured hypotheses. It must not replace the specialist agents or invent telemetry.

Flow:

```text
Reported Symptoms
      +
Application Context
      +
Specialist Findings
      +
Evidence
      |
      v
CloudOps Manager Reasoning
      |
      v
Structured Hypotheses
      |
      v
Shared Incident State
```

## Reasoning input

The Manager should provide Bedrock with:

- incident_id
- application_id
- environment
- region
- reported_symptoms
- application_context
- agent_findings
- evidence
- open_questions

The model should reason only over the supplied incident state and should clearly distinguish observed facts from hypotheses.

## Hypothesis schema

Each generated hypothesis uses:

| Field | Required | Meaning |
|---|---|---|
| hypothesis_id | yes | Stable incident-local ID such as HYP-001 |
| statement | yes | Concise causal hypothesis |
| status | yes | open, supported, weak, rejected, verified |
| supporting_findings | yes | Finding IDs that support the hypothesis |
| contradicting_findings | yes | Finding IDs that contradict it |
| confidence | yes | Numeric value from 0.0 to 1.0 |
| rationale | yes | Short evidence-grounded explanation |

Example shape:

```json
{
  "hypotheses": [
    {
      "hypothesis_id": "HYP-001",
      "statement": "Example causal hypothesis",
      "status": "open",
      "supporting_findings": [],
      "contradicting_findings": [],
      "confidence": 0.50,
      "rationale": "Example only; this must be based on supplied evidence."
    }
  ]
}
```

The example is schema-only and is not a conclusion about the current application.

## Output constraints

The reasoning response must:

1. Return valid JSON.
2. Return only the defined reasoning structure.
3. Use finding IDs that exist in the incident state when referencing evidence.
4. Never create fake resource IDs, telemetry values, log events, or alarm states.
5. Never treat missing telemetry as evidence of a zero value.
6. Keep hypotheses distinct from observed findings.
7. Generate multiple plausible hypotheses when the evidence is insufficient to establish one explanation.
8. State when available evidence is insufficient.
9. Keep confidence calibrated to the supplied evidence.
10. Avoid proposing destructive remediation in this reasoning step.

## Status semantics

- `open`: plausible and not sufficiently tested.
- `supported`: current evidence supports the hypothesis.
- `weak`: some evidence exists but important evidence is missing or contradictory.
- `rejected`: available evidence contradicts the hypothesis.
- `verified`: independently validated by a later investigation step.

The reasoning model should normally begin hypotheses as `open`, `supported`, or `weak`. `verified` should be reserved for later validation.

## Confidence

Confidence is a structured model estimate, not a statistical probability.

Interpretation:

- 0.00–0.24: very weak support
- 0.25–0.49: limited support
- 0.50–0.74: moderate support
- 0.75–1.00: strong support

These ranges are guidance for consistent output, not a claim that the model confidence is mathematically calibrated.

## Evidence references

The model should reference normalized finding IDs, for example:

```text
logs-customer-analytics-api-events
dynamodb-customer-analytics-data-active
eventbridge-customer-analytics-s3-upload-enabled
```

Raw telemetry remains in specialist evidence. The reasoning layer should use normalized findings for traceability and keep the incident state compact.

## Manager responsibilities

The Manager owns:

- loading the incident
- preparing the reasoning input
- invoking Bedrock
- validating the structured response
- storing hypotheses
- advancing the incident to the next reasoning state

Bedrock owns reasoning over supplied evidence only.

Specialists remain responsible for AWS investigation and evidence collection.

## Safety boundary

Reasoning must not execute AWS actions.

The reasoning phase can produce:

- hypotheses
- rationale
- evidence references
- open questions

Remediation planning and execution remain later phases with explicit safety controls and human approval where required.

## Current incident limitation

The validated incident `INC-AF76D3C6` contains:

- successful Observability findings
- successful Storage findings
- no hypotheses yet
- no independent hypothesis validation yet

The current telemetry also contains empty CloudWatch lookback results and zero returned metric datapoints. These should be represented as lack of observed data rather than definitive zero activity during reasoning.

## Next implementation

Implement a deterministic reasoning-input builder first, then add the Bedrock call and structured JSON validation.

Do not add remediation, automatic AWS changes, or a critic agent in this step.
