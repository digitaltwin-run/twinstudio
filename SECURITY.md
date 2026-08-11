# Security policy

This repository is a reference implementation, not a pre-hardened public SaaS.

Do not expose it publicly with `DEV_AUTH_BYPASS=true`, default secrets, plain HTTP, unauthenticated MQTT or the development Mailpit service.

Report vulnerabilities privately to the project owner. Include affected version, reproduction steps, impact and suggested containment. Do not include real credentials or proprietary project artifacts in a public issue.

See `docs/13_SECURITY.md` for the deployment checklist and LLM/adapter threat boundaries.
