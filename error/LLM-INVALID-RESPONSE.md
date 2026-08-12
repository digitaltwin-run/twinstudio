---
code: LLM-INVALID-RESPONSE
severity: error
automation: retry_after_validation
---

# Invalid structured response from LLM

The response did not match `ChangePlanProposal`. TwinStudio retained only its SHA-256 and validation diagnostic; it did not silently convert the response or execute a fallback plan.

```repair
REPAIR 1.0
FIND observation BY problem.correlation_id
VERIFY problem.details.response_sha256
VERIFY provider.strict_json_schema
RUN tests.change_planner
RETRY plan.once
REQUEST operator_review IF retry.failed
END
```
