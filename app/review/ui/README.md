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

The UI reads one bundle file:

```text
app/review/ui/data/review_bundle.json
```

The JSONL files in `app/review/ui/data/` remain the auditable pipeline source
tables. To refresh the bundled Gordon Wetzstein sample after regenerating entity
outputs, copy the JSONL source tables into `app/review/ui/data/`, then rebuild
the UI bundle:

```bash
cp OUTBOX_OR_RUN_DIR/people.jsonl app/review/ui/data/people.jsonl
cp OUTBOX_OR_RUN_DIR/relationships.jsonl app/review/ui/data/relationships.jsonl
cp OUTBOX_OR_RUN_DIR/organizations.jsonl app/review/ui/data/organizations.jsonl
cp OUTBOX_OR_RUN_DIR/evidence_sources.jsonl app/review/ui/data/evidence_sources.jsonl
cp OUTBOX_OR_RUN_DIR/resolution_decisions.jsonl app/review/ui/data/resolution_decisions.jsonl
cp OUTBOX_OR_RUN_DIR/profile_enrichments.jsonl app/review/ui/data/profile_enrichments.jsonl
python3 -m app.review.bundle
```

The bundle includes people, relationships, evidence, enrichments, reconciliation
warnings, and no-explicit-link people-search backfill candidates.
