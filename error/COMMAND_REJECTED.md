---
code: COMMAND_REJECTED
severity: error
automation: review-required
---

# Typed command rejected

The domain rejected the command because its payload, state transition, or Product Object Addressing scope is invalid.

```repair
REPAIR 1.0
READ problem.details
REFRESH project.snapshot
VERIFY command.contract
VERIFY command.scope
REQUEST operator_review IF semantic_change_required
END
```
