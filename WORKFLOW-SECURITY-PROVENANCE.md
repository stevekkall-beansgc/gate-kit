# Workflow scanner evidence and exceptions

Baseline: Gate Kit `38741affd2034f9b110b4a302ecfc08c4046f722`.
GitHub workflow-security run `36605329634`, inspected through `gh run view`
on 2026-10-02, recorded zizmor **1.28.0**, the pinned container digest
`sha256:8e6b3e4fb74d1aa5d23e83ea369f386c66eced0d1fb944d32cd8b2aac100b00d`,
offline mode, and all four checked-in workflows. Its regular-persona summary
was `No findings to report. Good job! (8 suppressed)`.

That summary does not enumerate eight reviewed ignore rules. The published
1.28.0 [registry source](https://github.com/zizmorcore/zizmor/blob/v1.28.0/crates/zizmor/src/registry.rs)
and [plain output source](https://github.com/zizmorcore/zizmor/blob/v1.28.0/crates/zizmor/src/output/plain.rs)
distinguish `ignored` (inline comments/configuration) from
`suppressed` (persona filtering). This repository contains
no inline `zizmor: ignore` directives and no configured rule ignores.

The sole pin-policy exception is:

| Rule | Exact scope | Rationale and remaining limit |
| --- | --- | --- |
| `unpinned-uses` / `ref-pin` | `stevekkall-beansgc/gate-kit/.github/workflows/compliance.yml`, currently `.github/workflows/gate.yml` job `compliance`, `@v0.4.11` | Existing internal annotated-release compatibility contract; third-party references retain `hash-pin`. Regression tests enforce this exact caller ref. The scanner policy matches the exact identity across files, not a wildcard namespace; future uses still require review. |

On 2026-10-02, the governed official macOS ARM64 zizmor 1.28.0 binary was
obtained as temporary release asset `485211655`; its archive matched published
SHA256 `54949bbd6b4c8527046bb8990bac9e0dab3eec787640f4e6199ae121dd1040be`.
With an empty environment except `PATH=/usr/bin:/bin`, `--offline --format=json
--no-exit-codes --no-progress --color=never --quiet -- .github/workflows`, the
regular persona returned zero findings, auditor returned eight, and auditor
with `--no-ignores` returned the same eight. Every result had `ignored: false`.
This reconciles the current candidate's eight persona-filtered results; the
historical log remains summary-only.

| Rule / severity / confidence / persona | Exact primary scope | Review rationale and disposition |
| --- | --- | --- |
| `excessive-permissions` / Medium / Medium / Pedantic | `compliance.yml:3`, workflow | Missing top-level permissions leaves caller/default token scope relevant. This is a real least-privilege review item; changing the reusable caller contract is outside this patch. Remains open for the owner. |
| `excessive-permissions` / Medium / Medium / Pedantic | `compliance.yml:21`, job `compliance` | Job inherits default permissions. Same open least-privilege item; no claim that caller settings universally constrain it. |
| `anonymous-definition` / Informational / High / Pedantic | `compliance.yml:21`, job `compliance` | Job lacks a display name; its stable job/check identity is an API. Naming is a usability follow-up, not a hidden exploit disposition or authorization to rename checks. |
| `self-hosted-runner` / Medium / High / Auditor | `test.yml:35`, job `local-validate` `runs-on` | Existing repository/main-push and runner identity guards reduce event exposure; persistence/ephemerality is not proved by source. Runner risk remains for operator review, not accepted by this document. |
| `anonymous-definition` / Informational / High / Pedantic | `test.yml:11`, job `unittest` | Stable job ID is visible but lacks a display name. Naming follow-up; check identity preserved. |
| `anonymous-definition` / Informational / High / Pedantic | `test.yml:33`, job `local-validate` | Same display-name follow-up; runner/check identity preserved. |
| `concurrency-limits` / Low / High / Pedantic | `test.yml:2`, workflow; related jobs at lines 11 and 33 | No concurrency setting; overlapping runs can consume resources. Cancellation/serialization policy needs owner review because it can change validation delivery. Remains open. |
| `concurrency-limits` / Low / High / Pedantic | `workflow-security.yml:3`, workflow; related job at line 14 | Report-only scans can overlap. Low resource/control follow-up; no concurrency behavior changed. |

Paths above are relative to `.github/workflows`; line numbers describe this
candidate. These are finding-review rationales, **not operator risk acceptance**.
No ignore or policy relaxation was added. Zero regular findings does not mean
eight auditor findings were fixed or independently accepted.

The source candidate adds an auditor-persona JSON step using the same immutable
offline container. It exposes persona-filtered findings to future reviewers
without changing the existing regular scan, `continue-on-error`, severity
policy, or compliance gate semantics. No step suppresses scanner execution
errors with `|| true`; `--no-exit-codes` keeps findings report-only.

For local enumeration, use the CONTRIBUTING container command with
`--persona=auditor --format=json --offline` in place of `--persona=regular`, retaining
the exact image, read-only mount and offline flags. Record process exit status
separately from findings. Review every rule/location/rationale before adding
an ignore. Do not broaden the exact pin exception.

The initial scanner check found no installed executable and no Docker daemon;
the later temporary native binary supplied the local evidence above. No scanner
was installed globally or service started. At the 2026-10-02 local candidate freeze,
the added Linux container step had not yet run on GitHub. The macOS binary scan
does not qualify it. Each release requires Linux execution evidence tied to its
exact commit, pinned image digest, scanner version, process exit status and
auditor JSON. Until release-specific evidence is recorded, Linux qualification
for that release remains unverified. Full history/dependency/rights review,
caller security and security ratings remain outside this evidence record.
