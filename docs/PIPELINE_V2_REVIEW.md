# Independent review — initial checkpoint

Tracking issue: https://github.com/chaygriff/buzz-test-project/issues/6 (read back as OPEN).

Verdict: **FAIL — release held**. Reviewed staged snapshot SHA-256 `ef44f53bd63705f0fe2c440fff0ec7ada4cd07791cc51e721de7c035f4778bba` against base `e80a4521d81c7dfff8703fde33c943366b20ff55`. The reviewer ran 155 tests plus 74 subtests against that snapshot. Later test counts do not supersede the findings without re-review.

## Blocking findings

1. Explicitly hidden roster rows and template-contained identity headings can establish evidence/ownership.
2. A matching page title can override contradictory primary h1 identity; another person's subsection can inherit page-wide claim ownership.
3. Robots Request-rate is parsed but neither enforced nor rejected.
4. A self-navigation link can suppress unsupported-roster review and make an empty JavaScript-only page appear complete.
5. Export verification accepts an incomplete hash inventory and can miss a deleted mandatory CSV.
6. Effective transport settings were absent from run fingerprint in the reviewed snapshot.

Parent independently reproduced findings 1–2 against the current local code. A fresh fix agent (not implementer/reviewer) is addressing 1–5 with RED/GREEN regressions. Finding 6 was already fixed after the review snapshot; the parent ran its specific regression successfully. Non-blocking EOF whitespace finding was also corrected and `git diff --cached --check` passed.

## Initial blocker resolution

A fresh fix agent addressed all initial findings with observed RED→GREEN regressions:

- Explicitly hidden/template/inert content cannot establish roster evidence or profile identity; ambiguous static visibility is review-only.
- Contradictory primary identities are unresolved and separately named person sections cannot contribute claims to the expected person.
- Unsupported robots Request-rate fails closed before content requests.
- Self/known roster links do not make an empty page successful; zero-candidate otherwise-successful bundles require review.
- Manifest verification requires mandatory JSONL/CSV/raw inventory and validates structural types.
- Effective transport settings are bound to the run fingerprint.

Local post-fix verification: **216 tests plus 76 subtests passed**, dependency check clean, and adversarial cases were directly reproduced as blocked/review outcomes. This is fix evidence, not final independent approval.

## Second review and sibling blocker resolution

The second reviewer independently confirmed the initial six blockers were fixed, then held release for four sibling issues:

- Closed native `details` descendants were treated as visible evidence.
- Manifest run ID, inputs and fingerprint were not internally bound to exported rows.
- Rehashed contradictory candidate CSV could pass verification.
- Candidate/link extraction caps yielded `needs_review`/success instead of `partial`/exit 2.

A second fresh fix agent added RED→GREEN coverage. Closed details content is now review-only while open details content remains eligible; manifest fingerprint/run attribution is checked; candidate CSV uses one deterministic generator for export and verification; and extraction truncation finishes jobs as `budget`, preserving bounded evidence and producing `partial`. Local post-fix gate: **238 tests plus 76 subtests passed**, dependency check clean.

## Third review and sibling blocker resolution

The third reviewer confirmed every original blocker and most second-review fixes, then found four more siblings:

- Closed native `dialog` content could become identity/evidence.
- Person-like ARIA-labelled regions could leak another person's claims.
- Deterministic job/observation IDs were not rederived during bundle verification.
- Extra unmanifested bundle files were accepted.

A third fresh fix agent added RED→GREEN regressions. Closed dialogs are now review-only; ARIA person regions enforce nearest ownership without establishing primary identity; verification rederives job/observation IDs from canonical content; and disk inventory must exactly match the manifest while rejecting symlinks/non-regular entries. `manifest.json` is intentionally outside its self-referential inventory. Local post-fix gate: **269 tests plus 76 subtests passed**, dependency check clean. This proves internal consistency, not authenticity against an attacker who reconstructs a coherent unsigned bundle; external signatures remain out of scope.

## Fourth review and sibling blocker resolution

The fourth reviewer confirmed every prior fix, then found three more siblings:

- Static native `popover` content could become visible evidence.
- Explicit person-labelled `region`/`group` roles on non-allowlisted tags could leak claims.
- Bundle verification did not validate the full v2 job domain or require one homepage root job per seed.

A fourth fresh fix agent added RED→GREEN regressions. Popover content is now review-only in static HTML; explicit region/group ownership is tag-independent and nearest-owner scoped; and bundle verification validates v2 inputs/seeds, exact job/observation schemas, kinds/statuses/payloads, seed IDs and exactly one deterministic homepage roster root per seed. Local post-fix gate: **309 tests plus 76 subtests passed**, dependency check clean.

## Fifth review and blocker resolution

The fifth reviewer confirmed the previous blocker classes and found three precise gaps:

- Claim nodes themselves, multi-reference ARIA names and presentational headings could bypass ownership rules.
- Equivalent seed URLs and invalid policy/config domains could produce noncanonical run inputs.
- Snapshot rows lacked an exact schema/domain check.

A fifth fresh fix agent added RED→GREEN regressions. Claim nodes now participate in nearest-owner checks; `aria-labelledby` references are joined in token order and fail closed if hidden/missing/duplicated; presentational headings cannot establish identity. Faculty homepages, scopes, origins, config and transport values now have canonical domains and duplicate canonical seeds are rejected. Snapshot rows require an exact schema, canonical URL/hash/path/status/content-type and timezone-aware retrieval time. Local post-fix gate: **357 tests plus 76 subtests passed**, dependency and compile checks clean.

## Sixth review and blocker resolution

The sixth independent reviewer blocked staged tree `1682b89455209317c1508ed97308ed9801580a28` on four precise gaps:

- Embedded stylesheet visibility was ignored, allowing CSS-hidden roster evidence to be promoted.
- `aria-labelledby` ownership accepted duplicate document IDs and could fall through an unresolved nearer owner.
- Snapshot verification accepted non-HTTP status integers such as 42.
- Top-level manifest validation accepted unknown fields.

A sixth fresh fix pass added observed RED→GREEN regressions. Static extraction now supports a bounded class/id selector subset for embedded visibility declarations; unsupported selectors, conditional rules and linked stylesheets fail closed to review rather than being fetched or treated as visible. ARIA ownership requires every referenced ID to resolve globally exactly once to visible, non-presentational content, and an unresolved nearest owner stops outward authorization. Snapshot status is exactly 0 for no response or 100–599 for an HTTP response, is enforced at storage and export verification, and a done job must reference a 2xx snapshot. Manifest top-level keys are exact. Local post-fix test gate: **380 tests plus 76 subtests passed**.

## Seventh review and blocker resolution

The seventh independent reviewer blocked staged tree `dee2aeabbbde4620176c0f7cd3eeb89fe81f72ae` on exactly three P1 findings:

- CSS comment removal treated `/*` and `*/` inside quoted CSS strings as comments, allowing a browser-hidden element to be promoted.
- Bundle verification accepted an observation rebound to a different job's otherwise-valid snapshot.
- A `done` job could omit its snapshot, while storage could create `done`/snapshot-status combinations that export verification later rejected.

A seventh fresh fix pass added observed RED→GREEN regressions. CSS scanning is now string-, escape- and comment-aware for the bounded static subset; malformed strings/comments, nested/at-rule semantics and unsupported selectors fail closed to review. Every observation must use its referenced job's exact snapshot in storage and bundle verification. A `done` job requires an existing 2xx snapshot at the runtime and SQLite boundaries as well as during export verification; SQLite also prevents later job/observation cross-rebinding. The focused gates passed, followed by a full local gate of **401 tests plus 76 subtests**.

## Eighth review and final blocker resolution

The eighth independent reviewer found three final blockers: retry attempts could crash while rebinding a job away from immutable prior observations; common clipping/zero-size CSS could promote hidden evidence; and observation payload URLs were not bound to the retained snapshot and requested job.

A final narrow RED→GREEN fix pass now retains an immutable job/snapshot association per attempt while allowing the job's current/final snapshot to advance. Retry-then-success, retry-then-failure and reopen-between-attempts regressions preserve both attempt receipts without leaving a running job. Static `clip`, `clip-path`, and zero width/height combined with hidden/clip overflow are review-only for inline and bounded embedded CSS. Candidate, claim, review and policy source URLs must be canonical and exactly match their snapshot; policy receipts also bind the canonical requested job URL, final result URL, redirect endpoint and attempt. Rehashed forged source attribution is rejected, while a valid requested-to-final redirect remains accepted.

The final local gate passed **419 tests plus 76 subtests**, followed by compilation, dependency, CLI-help and diff checks. No further independent review cycle is planned. This records resolution and local verification, not independent approval or remote CI. Commit, push, PR, merge and publication remain outside this pass.
