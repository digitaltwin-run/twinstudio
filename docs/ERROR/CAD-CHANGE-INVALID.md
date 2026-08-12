# CAD-CHANGE-INVALID

## Meaning

The typed change was compiled successfully, but the runtime CAD preflight found a blocking design constraint before `ChangeApplied`.

## Cause

The requested scalar value or an incomplete set of dependent scalar values would make the parametric housing invalid. For example, a lid lower than the auxiliary boss top datum cannot contain that boss.

## Resolution

Read `error.details.warnings` and create a new plan for the current revision. The normal NL planner derives supported dependencies such as moving an auxiliary boss with a lowered lid; direct API plans must include every required dependent parameter explicitly. The rejected request does not change the project revision, parameters, history, or visible CAD artifacts.
