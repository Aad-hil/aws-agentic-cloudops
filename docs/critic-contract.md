# Critic Agent Contract

## Purpose

Phase 5B introduces an independent Critic Agent after Bedrock hypothesis generation.

The Critic Agent does not replace specialist investigation and does not perform remediation. It challenges hypotheses produced by the reasoning layer against the persisted evidence.

Flow:

```text
Specialist Evidence
      +
Generated Hypotheses
      |
      v
Critic Agent
      |
      +-- evidence support check
      +-- contradiction check
      +-- unsupported claim detection
      +-- missing evidence identification
      |
      v
Hypothesis Critiques
      |
      v
Shared Incident State
```

## Input

The Critic Agent receives:

- incident metadata
- reported symptoms
- application context
- specialist findings
- evidence
- generated hypotheses
- open questions

The Critic Agent must reason only over this input.

## Output

Each critique contains:

| Field | Meaning |
|---|---|
| hypothesis_id | Existing hypothesis being challenged |
| verdict | supported, unsupported, or needs_more_evidence |
| issues | Specific reasoning or evidence problems |
| valid_supporting_findings | Findings that genuinely support the hypothesis |
| valid_contradicting_findings | Findings that contradict the hypothesis |
| missing_evidence | Evidence needed for validation |
| confidence | Critic confidence from 0.0 to 1.0 |
| rationale | Evidence-grounded explanation |

## Critical checks

The Critic Agent must specifically detect:

1. Missing telemetry being interpreted as zero activity.
2. A finding being cited as support when it actually contradicts the hypothesis.
3. Claims that have no supporting finding.
4. Hypotheses that overstate what an informational finding proves.
5. Hypotheses that require additional AWS evidence before validation.
6. Invalid finding references.

## Safety boundary

The Critic Agent:

- does not query AWS services directly
- does not change AWS resources
- does not execute remediation
- does not declare a root cause verified without sufficient evidence

The Manager remains responsible for incident state persistence and lifecycle transitions.

## Current implementation

Lambda:

`agents/critic/lambda_function.py`

Operation:

`critique_hypotheses`

Persistence field:

`hypothesis_critiques`

Incident event:

`hypotheses_critique_completed`

The first validation target is `INC-AF76D3C6`, whose generated hypotheses intentionally contain reasoning that the Critic should challenge, including treating empty metric datapoints as zero invocations.
