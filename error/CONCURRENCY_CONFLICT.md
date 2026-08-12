---
code: CONCURRENCY_CONFLICT
severity: warning
automation: safe
---

# Concurrent project update

The command used a stale stream version.

```repair
REPAIR 1.0
REFRESH project.snapshot
RECOMPUTE scoped_command
VERIFY command.scope
RETRY command.once
END
```
