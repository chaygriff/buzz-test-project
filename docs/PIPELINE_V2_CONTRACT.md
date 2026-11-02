# Collection pipeline v2 — completion contract

Scope: public faculty/lab discovery, conservative roster extraction, linked-profile enrichment, durable provenance, resumable bounded runs, and machine-readable exports. No new candidate UI, contact collection, outreach, conference/OpenAlex integration, or inferred recruiting eligibility.

The existing implementation and all historical datasets remain untouched. New implementation lives in `talent_pipeline/`; old commands remain available for comparison, not as the v2 execution path. Work starts from the fetched remote main; the newer destination-enrichment checkout remains preserved separately.

## Acceptance criteria

1. A single CLI starts or resumes a collection run from a validated faculty CSV; run inputs and policy are bound to the run. Explicit new-run creates a refresh without erasing history.
2. A durable SQLite frontier records jobs, attempts, blocked/failed/unsupported outcomes and completion. Restart does not repeat successful work; interrupted in-flight jobs can be resumed. A bounded/incomplete crawl never reports complete.
3. Every network request is public HTTP(S), robots-checked, throttled, bounded by size/time/attempt/page/profile budgets, with redirects checked before following. Unavailable robots fails closed. Platform profiles that prohibit automated access are identifiers only.
4. Every promoted roster record has exact visible source evidence and a content-addressed raw snapshot. Ambiguous and unsupported extraction remains a review item rather than an invented person or relationship. Shared names alone never merge identities.
5. Linked-profile enrichment records source observations and verifies page identity before promoting self-declared links or employment claims. Missing employer/title is unknown; roster destinations are historical source claims, not current employment.
6. Exports contain JSONL evidence, candidates, claims, jobs and review items; CSV candidates; and a manifest with hashes/counts/status. Exports are published to a new immutable directory only after validation. Partial results are explicitly marked and return a non-success collection exit status.
7. Automated regression tests exercise real extraction/storage/orchestration, deterministic transport fixtures and failure paths. A bounded real public-source smoke run must be distinguished from fixture validation; blocked sources remain blocked, never replaced by invented data.

## Evidence semantics

- A roster link establishes a source association, not automatically a verified external identity.
- A candidate-owned page with an exact normalized name in its title or primary heading may support self-declared profile/employment claims. This is source attribution, not independent employment verification.
- Employer/title claims retain exact evidence, source, observation time and verification state. No claim of currentness is derived solely from a lab's alumni list.
- No percentages or heuristic scores are presented as calibrated truth probabilities.

## Operational boundaries

Single local operator; one writer per run. Credentials are supplied through the environment, never committed (v2 requires none). Public seeds must be operator-authorized; robots permission does not replace checking site terms. No scheduled or paid requests are configured automatically. Default crawl/profile budgets are deliberately small.

## Delivery verification

Record exact commands/results in `docs/PIPELINE_V2_VERIFICATION.md`. Do not call the entire project complete if any criterion is unverified. Preserve the external GitHub issue/PR state separately from local implementation state. Owner retains merge authority.
