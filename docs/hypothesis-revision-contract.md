# Hypothesis Revision Agent Contract

## Purpose

The Hypothesis Revision Agent revises hypotheses after independent Critic feedback.

Flow:

Specialist Evidence -> Generated Hypotheses -> Critic Agent -> Hypothesis Critiques -> Hypothesis Revision Agent -> Revised Hypotheses

The revision agent does not collect AWS telemetry and does not perform remediation.

## Revision rules

1. Reason only from persisted incident state.
2. Critic feedback is an independent challenge, not automatically ground truth.
3. Correct unsupported evidence references.
4. Never treat missing telemetry as zero activity.
5. Do not invent missing evidence.
6. Preserve existing hypothesis_id values.
7. Return exactly one result for each current hypothesis.
8. The agent MUST NOT create new hypotheses or introduce a different causal explanation.
9. Each result must declare a revision_action: keep, revise, or reject.
10. Use keep when no substantive correction is required; do not change a hypothesis merely because the agent was assigned a revision task.
11. Use revise only to correct the existing hypothesis using supplied evidence while preserving its original causal scope.
12. Use reject when the existing hypothesis is unsupported or contradicted; do not replace it with another cause.
13. If more evidence is required, keep the hypothesis as open/weak rather than inventing an explanation.
14. A hypothesis may become weak or rejected when evidence warrants it.
15. Confidence is reasoning confidence, not a probability.

## Revision action semantics

- `keep`: preserve the existing hypothesis because the Critic identified no substantive problem.
- `revise`: correct wording, evidence references, status, confidence, or rationale for the existing hypothesis without changing it into a different causal hypothesis.
- `reject`: mark the existing hypothesis as rejected when available evidence does not support it or contradicts it. Do not create a replacement hypothesis.

The Manager is responsible for requesting additional specialist investigation when a hypothesis remains unresolved. The Revision Agent must not fill evidence gaps by generating new hypotheses.

## Revision limit

The POC allows a maximum of 2 revision rounds per incident.
If evidence is still insufficient after the revision loop, the next phase should create
a targeted investigation task rather than repeatedly asking the model to rewrite the hypothesis.

## Persistence

Revised hypotheses replace the current hypotheses field.
Every revision is appended to hypothesis_revision_history with the revision number,
timestamp, revised hypotheses, and the Critic verdicts that triggered the revision.

## Safety boundary

The Revision Agent does not query AWS services, modify AWS resources, execute remediation,
or declare a root cause verified without independent evidence.

The next phase is Root Cause Assessment.