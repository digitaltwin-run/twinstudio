---
code: INTERNAL_ERROR
severity: critical
automation: prohibited
---

# Internal server error

An unhandled exception crossed the application boundary. Use the correlation identifier to find the structured server log; do not expose exception internals to the browser.

```repair
REPAIR 1.0
FIND log BY problem.correlation_id
VERIFY failure.reproducible
RUN tests.relevant
REQUEST operator_review
END
```
