# Phase 1 Plan

Source: `Talent_Network_Collector_Phase1_Agent_Spec.md` attached in Buzz.

## Mission

Build a deterministic, evidence-backed collection pipeline for public pages that
connect AI faculty, labs, students, alumni, postdocs, and researchers.

## Guardrails

- Evidence over inference.
- Every extracted fact needs provenance.
- Respect robots.txt and site terms.
- Preserve raw HTML before parsing.
- Do not add AI extraction until parsed page output has been reviewed.

## Implemented Milestone Coverage

Milestone 1:

- CSV seed loader
- robots.txt handler
- same-site crawler
- cache for raw HTML and metadata
- crawl log JSONL
- CLI entry point

Milestone 2 foundation:

- relevant-link discovery heuristics
- heading hierarchy parser
- structured section block export
- first-pass supervised-student relationship normalization

## Next Steps

1. Replace `seeds/faculty.example.csv` with an initial curated seed dataset.
2. Run a small crawl against 2-3 faculty/lab sites.
3. Review `sections.jsonl` manually for parser quality.
4. Review `relationships.jsonl` manually for relationship normalization quality.
5. Add selector, parser, and normalizer improvements based on reviewed pages.
6. Approve or reject a later AI extraction milestone only after review.
