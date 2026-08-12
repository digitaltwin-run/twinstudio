---
code: UI_ARTIFACT_LOAD_FAILED
severity: error
automation: safe-read-only
---

# UI artifact failed to load

The browser could not fetch or parse a 2D/3D artifact required by the active view. The `UIContext.artifacts` list identifies the URI, path, purpose and status.

```repair
REPAIR 1.0
READ ui_context.artifacts WHERE status=failed
VERIFY project.artifact_registry
VERIFY artifact.download
VERIFY artifact.media_type
VERIFY viewer.parser_support
RELOAD active_view.once
END
```
