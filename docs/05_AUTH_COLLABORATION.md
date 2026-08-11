# 05 — Authentication and collaboration

## Roles

| Role | Intended capability |
|---|---|
| reader | View tree/spec/events and download permitted artifacts |
| editor | Add annotations, resolve selections, plan/apply draft changes, run simulations and generate artifacts |
| admin | Editor capabilities plus invitations, memberships and approvals |
| creator | Full control, creator-only destructive/ownership operations |

Project membership is event-sourced. A role is evaluated per project rather than globally.

## Email approval flow

1. External person submits project ID, email, requested role and optional decision-maker email.
2. The application chooses a creator/admin and stores a pending invitation.
3. The decision-maker receives approve/reject links.
4. Approval sends a one-time access link to the requestor.
5. Accepting creates the account and project membership, a browser session and a personal API token.
6. The personal token is shown once and can be used as the HTTP Basic password with the email as username.

This meets the requested low-friction “email only” onboarding while preserving an explicit decision event.

## Basic authentication

Basic authentication does **not** transmit an account password in this design. It transmits `email:personal-access-token` over HTTP headers. It must be used only over TLS.

## Collaborative editing

The MVP broadcasts stored events over project WebSockets. Concurrent writes use optimistic stream versions. Recommended next steps:

- comment threads and mentions;
- region/feature soft locks with expiry;
- approval states on change plans;
- branch/review/merge workflow;
- audit filters and notifications;
- token management and revocation UI;
- project groups and organization policies.

## Production hardening

Before exposing the system publicly:

- disable `DEV_AUTH_BYPASS`;
- require HTTPS and secure cookies;
- add CSRF protection for session-authenticated mutations;
- bind one-time links to short TTL and rate limits;
- hash/rotate tokens and expose revocation;
- use a production identity provider where appropriate;
- protect invitation endpoints from enumeration and abuse;
- configure SPF/DKIM/DMARC for mail;
- separate service accounts from human accounts;
- apply tenant-aware authorization to every artifact backend and WebSocket connection.
