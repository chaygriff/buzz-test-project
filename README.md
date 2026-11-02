# Talent Network Collector v2

Evidence-backed **collection pipeline**, not a recruiting UI. Starts with public faculty/lab pages, discovers roster pages, extracts conservative candidate observations, enriches explicitly linked profiles, and publishes self-contained evidence bundles.

V2 is implemented independently in `talent_pipeline/`. The historical `app/` implementation and existing datasets remain available for comparison; the new command does **not** execute the old crawler, parser, identity resolver, or enrichment functions. The more recent destination-enrichment checkout remains separate and unchanged. No historical data migration or deletion is performed.

## Install and test

Python 3.11+ on macOS/Linux (local advisory writer locking uses `fcntl`).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/talent-collect --help
```

The full test command is pytest, not unittest discovery: extraction tests include parametrized pytest functions. CI exercises Python 3.11–3.14; local results and live-test limitations are in [verification](docs/PIPELINE_V2_VERIFICATION.md).

## Operator-approved seeds

Create a CSV:

```csv
faculty_name,faculty_institution,faculty_homepage,terms_approved,scope_path
Example Faculty,Example University,https://lab.example/faculty/,false,/faculty/
```

This deliberately **will not run** until the operator reviews source terms/eligibility and changes `terms_approved` to `true`. Public visibility and robots permission are not substitutes for that review. Do not mark an unreviewed source approved merely to make the pipeline run.

- `faculty_name`, `faculty_institution`, `faculty_homepage`, `terms_approved` are required.
- `scope_path` is optional; it defaults to the homepage directory. Use a narrow faculty/lab directory on shared university hosts.
- Each source observation retains its own faculty context. Duplicate seeds are rejected.
- Private addresses, credentials in URLs, non-HTTP(S) URLs and nondefault ports cannot be fetched.

## Start, resume, refresh

```sh
.venv/bin/talent-collect run \
  --seeds approved-faculty.csv \
  --state data/v2 \
  --max-pages-per-seed 8 \
  --max-profiles-per-seed 10
```

The CLI prints a JSON receipt containing `run_id`, `bundle`, `status`, and counts. Repeat the same command to resume: completed jobs are not fetched again. `--new-run` starts an explicit refresh and preserves history. Different seeds, budgets, approved origins or transport limits create a different run fingerprint.

Only seed origins are initially eligible. To inspect an external linked personal website, review its source eligibility and add its **exact origin**:

```sh
.venv/bin/talent-collect run --seeds approved-faculty.csv --state data/v2 \
  --approve-origin https://researcher.example
```

Adding an approval creates a new run rather than rewriting a previous partial run. Redirect origins also need approval; same-site roster scope still applies. LinkedIn, GitHub account pages and Google Scholar are identifiers only and are not fetched. GitHub Pages personal sites are distinct origins and can be approved individually.

### Completion states

| Status | Meaning | CLI exit |
|---|---|---|
| `complete` | Every queued job completed; no explicit review holdouts | 0 |
| `needs_review` | Every job completed but ambiguity, missing employment or unsupported extraction remains | 0 |
| `partial` | A job was blocked, unsupported, failed, unfinished or stopped by budget | 2 |
| Input/storage/verification error | No successful collection receipt | 1 |

`complete` is **bounded processing completion**, not a claim of exhaustive worldwide coverage or independently verified employment. Budget-limited traversal is `partial`. Failures consume the same fetch-attempt budgets as successes. Exhausted runs remain explicit outcomes; adjust policy/budget or request a fresh run rather than silently resetting counters.

## Data and evidence

Each state directory contains an SQLite ledger and content-addressed `raw/` objects. Observation metadata is append-only; job state is mutable. One local writer per state directory is enforced. Interrupted active jobs recover on resume; completed jobs remain completed. A request that finished before a process interruption but not before the job commit may be repeated. Filesystem/power-loss durability and backup policy require operator infrastructure testing.

Source-local subject IDs intentionally do not merge people across faculty sources solely because names or text match. A roster URL is an identity lead. A full-name match on a linked page permits **self-declared** assertions, not independent identity or employment verification. Same-name collisions remain a fundamental limitation; source context must be reviewed.

Roster evidence preserves the observed section, normalized role where explicit, source text, DOM locator, faculty context, parser version, raw snapshot and retrieval time. Alumni destinations remain roster evidence—not current-employer claims. Profile claims come from labelled page-owned links, exact-name JSON-LD Person metadata, or conservative first-person affiliation statements. Employer/title claims remain raw where no safe structured extraction exists. Missing data is unknown, never guessed.

Unsupported or ambiguous roster units are exported for review. Only static HTML is supported; no JavaScript execution or computed CSS visibility analysis. Case/layout/name recognition intentionally favors holdouts. No contact-detail extraction, outreach, paid enrichment, background scheduling or conference/OpenAlex discovery is included.

## Export and verify

```sh
.venv/bin/talent-collect export --state data/v2 --run-id RUN_ID
.venv/bin/talent-collect verify data/v2/exports/BUNDLE_DIRECTORY
```

Exports are staged, validated and atomically renamed into a new directory. Existing bundles are not overwritten. Each contains:

- `manifest.json`: inputs, fingerprint, status, counts and file hashes.
- `candidates.jsonl` / `candidates.csv`: roster candidate observations, not a deduplicated worldwide person directory.
- `claims.jsonl`: attributed profile assertions.
- `review.jsonl`: unresolved/rejected/unsupported evidence.
- `jobs.jsonl`, `policies.jsonl`, `observations.jsonl`, `snapshots.jsonl`.
- Referenced `raw/` files, so the bundle is self-contained.

Verification checks file/snapshot hashes, counts, unique record IDs, evidence references, claim-subject references, derived-table consistency and completion state. CSV values are protected against spreadsheet formula interpretation; JSONL preserves original text. Bundle hashes detect accidental corruption but are not cryptographic signatures proving authenticity against a party able to rewrite the entire manifest.

## Transport limits

Every target is manually redirect-checked, approval-gated, scope-checked and robots-checked before its content request. DNS addresses must all be public and the chosen address is pinned to the connection with the original TLS hostname. Requests use bounded time/body/hop limits and per-origin throttling. Missing robots (404) permits; unavailable, throttled, malformed or ambiguous policy denies.

Conservative robots parsing currently rejects wildcard/end-anchor rules and fractional crawl delays. This can block otherwise permissible sites; it never grants permission by ignoring an unsupported rule. Robots is fetched for each hop. Throttling is serial and local to one Fetcher instance, not distributed or persisted across separate invocations. Requests use no login, cookies, proxies or automatic redirects.

See the [completion contract](docs/PIPELINE_V2_CONTRACT.md) and [verification record](docs/PIPELINE_V2_VERIFICATION.md) before expanding collection scope.
