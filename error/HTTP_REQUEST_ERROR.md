---
code: HTTP_REQUEST_ERROR
severity: error
automation: review-required
---

# HTTP request error

The server rejected an HTTP request without a more specific domain code. Inspect the status, correlation identifier and structured details before retrying.

```repair
REPAIR 1.0
READ problem.status_code
READ problem.details
VERIFY request.contract
RETRY request.once IF problem.retryable
END
```
