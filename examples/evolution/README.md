# TwinStudio evolution examples

The three `rpi5-hinge-evolution` files are semantically equivalent representations of one `EvolutionProgram`:

- `.twin` — concise line-oriented TwinScript 1.0;
- `.yaml` — canonical declarative document;
- `.json` — canonical JSON matching `schemas/twin-dsl.schema.json`.

Preview from the CLI:

```bash
twinstudio dsl-preview examples/evolution/rpi5-hinge-evolution.twin --project-id demo-rpi5
```

Preview through REST:

```bash
curl -s http://localhost:8000/api/v1/projects/demo-rpi5/dsl/preview \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{"source_format":"twin","source":"TWINSCRIPT 1.0\nNAME \"Minimal example\"\nPROJECT demo-rpi5 REVISION main\nFOCUS \"poa://demo/demo-rpi5@main/part/base\"\nGOAL VERB improve OBJECT \"base\" OUTCOME \"simpler support-free printing\"\nEND\n"}
JSON
```

A preview creates no events and changes no product data. Use the apply endpoint with `dry_run=false` only after reviewing the compiled evolution run, lifecycle blueprint and typed change plans.
