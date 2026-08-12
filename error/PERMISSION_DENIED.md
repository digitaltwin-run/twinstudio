---
code: PERMISSION_DENIED
severity: error
automation: prohibited
---

# Permission denied

The authenticated principal lacks the permission required for this project operation. Do not bypass authorization. Inspect the membership and request access through the normal approval flow.

```repair
REPAIR 1.0
VERIFY identity.current
VERIFY project.membership
REQUEST access.approval
VERIFY operation.retry_as_authorized_identity
END
```
