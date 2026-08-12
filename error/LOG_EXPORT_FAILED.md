---
code: LOG_EXPORT_FAILED
severity: error
automation: safe-read-only
---

# DSL log export failed

The browser could not retrieve recent project observations or write the combined UI action and TWINOBS trace to the clipboard. The direct `Pobierz logi DSL` action remains available and does not require clipboard permission.

```repair
REPAIR 1.0
VERIFY project.read
VERIFY /api/v1/projects/{project_id}/logs.dsl
VERIFY browser.clipboard_permission
READ ui_context.route
RETRY copy_logs.once
END
```
