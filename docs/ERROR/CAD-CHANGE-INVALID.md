# CAD-CHANGE-INVALID

## Meaning

The typed change was compiled successfully, but the runtime CAD preflight found a blocking design constraint before `ChangeApplied`.

## Cause

The requested scalar value would make the parametric housing invalid. For example, a lid lower than the auxiliary boss top datum cannot contain that boss.

## Resolution

Read `error.details.warnings`, keep the selected component, and submit a value satisfying the reported constraint. The rejected request does not change the project revision, parameters, history, or visible CAD artifacts.
