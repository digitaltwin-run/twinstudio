---
code: REQUEST_VALIDATION_FAILED
severity: error
automation: safe
---

# Request validation failed

The request does not match the declared API schema. Use the validation paths in `problem.details.errors` to correct fields and types.

```repair
REPAIR 1.0
READ api.schema
MAP problem.details.errors TO request.fields
CORRECT request.fields
RETRY request.once
END
```
