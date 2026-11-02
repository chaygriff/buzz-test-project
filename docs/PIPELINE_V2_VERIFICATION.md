# Pipeline v2 verification record

## Repository and isolation

- Worktree: `/Users/chan/projects/talent-network-collector-v2`
- Branch: `rebuild/collection-pipeline-v2`
- Base: fetched remote `main`, `e80a452`.
- Original main, enrichment and destination-enrichment worktrees and historical datasets were not modified.
- Live GitHub discovery before implementation: no issues, no open PRs, five merged PRs; the owner's only returned project board was unrelated Kalshi work. No collection board existed in that listing.

## Local automated verification

Installed a fresh project-local environment using:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
.venv/bin/talent-collect --help
```

Latest full execution at this checkpoint after the deterministic crawl-delay fix: **424 passed, 78 subtests passed**. Focused regressions were observed failing before implementation and passing afterward. New coverage includes immutable per-attempt snapshot provenance across retry success, terminal retry failure and process reopen; inline and embedded clipping/zero-size hiding; forged payload source attribution and invalid policy attempt domains; valid requested-to-final redirects; and cross-version crawl-delay handling for wildcard, exact, combined, duplicate, irrelevant and reordered robots groups. Dependency, compilation, CLI-help and diff checks are recorded only from local commands; remote CI has not been run at this checkpoint.

Focused tests cover:

- Durable resume/recovery, source-local identities for identical text across faculty contexts, transport-policy fingerprint changes, and completed-run zero-request resume.
- Attempt budgets including failed requests and retries without refunding prior failures.
- Single-writer exclusion; append-only evidence metadata; failed disk write before raw publication; content hashes across reopen.
- Full CLI → real network-policy logic with synthetic single-hop transport → actual HTML extraction → SQLite → export → verification.
- Robots 429 → partial export and zero content-page requests.
- Atomic export interruption cleanup and rejection of corrupted retained raw evidence before publication.
- Robots allow/deny/status/timeouts/malformed rules, redirect/scope/private-address gates, public-address pinning/TLS hostname, request deadlines and size limits.
- Conservative names/roles/sections, malformed lists, explicit coadvisors, publication exclusion, profile identity mismatch, JSON-LD and first-person self-declared claims, original-source DOM locators.

All `.example` fixture people and organizations are synthetic test inputs, never reported as collected candidates.

## Real public-source smoke check (not a production enrichment run)

Read-only compatibility probe against the original project's seed, `https://jiajunwu.com/`:

1. Robots returned 200, `User-agent: *` and `Allow: /`.
2. A deliberately smaller 1,000,000-byte test budget failed closed with `body_too_large`.
3. The standard 2,000,000-byte budget returned HTTP 200 HTML, **1,243,453 bytes**.
4. Retained raw SHA-256: `d733b2f6c73da8bb283c3b978b61c06598c86968fd1eac76d6a7439816f41486`.
5. Initial extraction exposed an unsupported live layout rather than returning useful roster rows. Added observed RED→GREEN regressions for `Group` with explicit `div.title` subsection labels, omitted list-end tags, and explicit coadvisor/destination prose.
6. Offline replay of that retained real response now yields **46 source-attributed candidate observations**. This is a source observation count, not 46 independently verified identities, current roles, or qualified recruiting candidates.

Probe receipts and raw data are retained locally under `data/v2-live-probe/` (ignored by git). An export built by replaying the retained snapshot preserves the original retrieval timestamp and labels every candidate for pending enrichment:

```text
run_id: 2034c78e63bd444091af26550a67b360
status: needs_review
candidates: 46
claims: 0
review: 46
snapshots: 1
```

The bundle is listed in `data/v2-live-probe/live-roster-bundle.json`. This artifact was produced by explicit offline snapshot replay/storage, **not** by a full live CLI enrichment run. No additional candidate-origin approvals were supplied and no candidate profile pages were requested during this smoke check. Production source-eligibility/terms review remains an operator responsibility; a limited compatibility probe is not a legal-permission determination.

## Remaining release gates at this checkpoint

- The eighth findings are resolved and no further independent review cycle is planned; this is not a claim of independent approval.
- Full live enrichment across individually approved candidate origins has not been performed.
- Remote CI has not been dispatched/verified.
- Recognition remains conservative and static-HTML only; no claim of universal roster coverage.
- Existing destination-enrichment datasets are preserved, not migrated into v2 automatically.
- Throttling is local to a Fetcher instance and is not persisted across new processes.
- Filesystem power-loss recovery and long-running production workload behavior have not been validated.

This is evidence for a working bounded collection implementation, not a declaration that every acceptance criterion or production rollout gate has passed.
