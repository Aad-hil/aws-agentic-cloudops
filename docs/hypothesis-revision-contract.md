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
7. Return exactly one revised hypothesis for each current hypothesis.
8. A hypothesis may become weak or rejected when evidence warrants it.
9. A hypothesis may remain open when additional investigation is required.
10. Confidence is reasoning confidence, not a probability.

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