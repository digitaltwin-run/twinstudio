---
code: DB_ROLE_MISSING
severity: critical
automation: guarded
---

# PostgreSQL role is missing

The configured database user does not exist in the PostgreSQL cluster. This commonly happens when an existing Docker volume is reused with credentials different from the current Compose defaults.

```repair
REPAIR 1.0
VERIFY postgres.authenticated_query
CHOOSE database.credentials.align_with_existing_volume
RESTART compose.postgres_and_dependants
VERIFY postgres.authenticated_query
VERIFY app.health
END
```

Do not create or delete database roles automatically. Read `TWINSTUDIO_POSTGRES_*` and `TWINSTUDIO_COMPOSE_DATABASE_URL`, align them with the initialized volume, and require operator approval before changing credentials.
