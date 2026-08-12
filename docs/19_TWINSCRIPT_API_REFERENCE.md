# 19 — TwinScript, schema and API reference

## Canonical model

All syntax forms compile to `TwinDslDocument`:

```yaml
api_version: twinstudio.io/v1alpha1
kind: EvolutionProgram
metadata:
  name: Example evolution
  namespace: default
spec:
  project_id: demo-rpi5
  base_revision: main
  targets:
    - poa://demo/demo-rpi5@main/part/base
  goal:
    statement: improve base manufacturability
```

Canonical schema: `schemas/twin-dsl.schema.json`. Text grammar: `schemas/twinscript.ebnf`.

## TwinScript directives

Core identity and scope:

```text
TWINSCRIPT 1.0
NAME "Program name"
NAMESPACE demo
LABEL domain=mechanical
ANNOTATION intent="Explore alternatives"
PROJECT demo-rpi5 REVISION main
FOCUS "poa://demo/demo-rpi5@main/part/base"
```

Goal framing:

```text
GOAL VERB improve OBJECT "front hinge" OUTCOME "support-free printing"
OUTCOME "opening above 190 degrees"
PRESERVE "2 mm wall thickness"
AVOID "hinge collision"
ASSUME "the current mechanism is not mandatory"
CONSTRAINT "two separately printable parts"
```

Search and lenses:

```text
METHODS goal_ladder,object_decomposition,bidirectional_graph,feature_lenses,adjacent_possible,brainswarm,mutation,recombination,experiment
SEED_VERBS improve,open,fasten,manufacture
LENSES shape,connectivity_among_parts,human_use,aesthetics
DIMENSIONS manufacturability,serviceability,reversibility,adjacent_possible
LENS_OPTIONS SOURCE true EXTENSIONS true ASSUMPTIONS true MAX 96
RESOURCE_OPTIONS DESCENDANTS true FEATURES true PARAMETERS true MATERIALS true PROCESSES true ARTIFACTS true REQUIREMENTS true EVIDENCE true HUMAN true ENVIRONMENT true MAX 300
SEARCH UP 1 DOWN 2 SIDEWAYS 1 MAX 48 OPPOSITES true
```

Evolution and evaluation:

```text
EVOLVE POPULATION 12 GENERATIONS 4 OFFSPRING 2 MUTATION 0.82 CROSSOVER 0.35 SEED 17 ADJACENT_DEPTH 2
OPERATOR reframe_goal WEIGHT 1.0 ENABLED true
WEIGHT feasibility 0.20
WEIGHT manufacturability 0.18
SELECT_TOP 5
MIN_SCORE 0.25
```

Lifecycle and gates:

```text
LIFECYCLE hardware-product START detailed_design TARGET verification APPROVAL true
ENABLE_STAGE design_review,prototype,verification
DISABLE_STAGE pilot
GATE convergence CHECK="at least three mechanisms remain" ROLE=creator,admin BLOCKING=true
```

Explicit changes and realization:

```text
CHANGE set_parameter "poa://demo/demo-rpi5@main/part/base" parameter=wall_thickness value=2 unit=mm
VERIFY "slice both parts without model repair"
REALIZE change_plan DRY_RUN true APPROVAL true MAX_PLANS 3
ALLOW_OPERATIONS set_parameter,add_feature,boolean_cut,add_test
OUTPUT GRAPHS json,dot,mermaid REPORTS json,markdown,csv
PERSIST_ARTIFACTS true
INCLUDE_CHANGE_PLANS true
NOTE "Candidates require physical validation"
END
```

Backslash line continuation is supported. Keywords are case-insensitive; quoted strings should be used for values containing spaces.

## REST

### Catalog and syntax

```text
GET /api/v1/evolution/catalog
GET /api/v1/dsl/schema
GET /api/v1/dsl/grammar
POST /api/v1/dsl/parse
```

`POST /api/v1/dsl/parse`:

```json
{
  "source_format": "twin",
  "source": "TWINSCRIPT 1.0\nNAME \"Example\"\n..."
}
```

### Project compilation

```text
POST /api/v1/projects/{project_id}/dsl/preview
POST /api/v1/projects/{project_id}/dsl/apply
POST /api/v1/projects/{project_id}/evolution/preview
```

Preview returns diagnostics, canonical document, `EvolutionRun`, `LifecycleBlueprint`, typed `ChangePlan` previews and an execution record. It creates no events.

Apply body:

```json
{
  "source_format": "twin",
  "source": "...",
  "dry_run": false,
  "generate_artifacts": true
}
```

With `dry_run=false`, permissions are checked and the API can record the run, lifecycle blueprint, plans, artifacts and DSL execution. `auto_apply_safe` remains restricted to allow-listed scalar patches.

### Run and lifecycle queries

```text
GET  /api/v1/projects/{project_id}/evolution/runs
GET  /api/v1/projects/{project_id}/evolution/runs/{run_id}
GET  /api/v1/projects/{project_id}/evolution/runs/{run_id}/graph?format=json|dot|mermaid
POST /api/v1/projects/{project_id}/evolution/runs/{run_id}/candidates/{candidate_id}/change-plan
GET  /api/v1/projects/{project_id}/lifecycles
POST /api/v1/projects/{project_id}/lifecycles/transition
```

## CLI

```bash
twinstudio dsl-schema
twinstudio dsl-grammar
twinstudio dsl-parse program.twin
twinstudio dsl-preview program.twin --project-id demo-rpi5
twinstudio dsl-apply program.twin --project-id demo-rpi5 --execute
twinstudio evolution-runs --project-id demo-rpi5
twinstudio lifecycles --project-id demo-rpi5
```

The `lps` executable remains a deprecated alias for migration.

## MCP tools

Evolution-related tools:

```text
get_evolution_catalog
get_dsl_schema
preview_dsl
list_evolution_runs
get_lifecycle_blueprints
candidate_to_change_plan
```

They share the same permission checks and domain services as REST and CLI. MCP does not bypass POA scope, lifecycle approvals or typed plan validation.

## Diagnostics

Diagnostics contain:

```json
{
  "severity": "blocking",
  "code": "scope.target_outside_project",
  "message": "...",
  "line": 12,
  "column": null,
  "path": "spec.targets.0",
  "hint": "..."
}
```

Severities: `info`, `warning`, `error`, `blocking`. Compilation and persistence stop on `error` or `blocking` diagnostics.
