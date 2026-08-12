---
code: RESOURCE_NOT_FOUND
severity: error
automation: safe-read-only
---

# Resource not found

The requested API resource or artifact does not exist at the resolved address.

```repair
REPAIR 1.0
VERIFY request.address
VERIFY project.artifact_registry
VERIFY artifact.file_exists
CHOOSE registry.address WHEN available
END
```
