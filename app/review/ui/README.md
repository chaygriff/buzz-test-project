# Talent Network Review UI

Small static UI for visually inspecting Phase 1 collector outputs.

Run locally from the repository root:

```bash
python3 -m http.server 8765 --directory app/review/ui
```

Then open:

```text
http://localhost:8765
```

The bundled sample data is the Gordon Wetzstein seed generated from the current
pipeline. To refresh it after regenerating entity outputs, copy the JSONL files
into `app/review/ui/data/`:

```bash
cp OUTBOX_OR_RUN_DIR/people.jsonl app/review/ui/data/people.jsonl
cp OUTBOX_OR_RUN_DIR/relationships.jsonl app/review/ui/data/relationships.jsonl
cp OUTBOX_OR_RUN_DIR/organizations.jsonl app/review/ui/data/organizations.jsonl
cp OUTBOX_OR_RUN_DIR/evidence_sources.jsonl app/review/ui/data/evidence_sources.jsonl
cp OUTBOX_OR_RUN_DIR/resolution_decisions.jsonl app/review/ui/data/resolution_decisions.jsonl
```
