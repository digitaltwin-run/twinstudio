---
code: PROJECT_NOT_FOUND
severity: error
automation: safe-read-only
---

# Project not found

The requested project stream does not exist or has not been seeded.

```repair
REPAIR 1.0
VERIFY project.list
VERIFY project.identifier
CHOOSE project.select_existing
OR seed.example_project WITH operator_approval
VERIFY project.read
END
```
