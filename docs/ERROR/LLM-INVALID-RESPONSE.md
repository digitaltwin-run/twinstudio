# LLM-INVALID-RESPONSE

## Meaning

The model response failed the strict `ChangePlanProposal` schema and was not converted into a plan.

## Cause

The response was malformed or attempted to set runtime-owned identity, approval or authority fields.

## Resolution

Inspect the response SHA-256 and validation diagnostic, verify the configured model supports strict JSON Schema, then retry. Never copy fields from the rejected response into a runtime plan.
