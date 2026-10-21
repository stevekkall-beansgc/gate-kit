# QA Kit caller runtime proposal

This local candidate changes only the `qa-kit` caller's runtime/provenance profile
in the current reusable workflow source. It does not move any tag, change checker
or fixture pins, rename checks, alter events, enroll a repository, remove a gate,
change cancellation, or claim CI savings. Other callers retain their existing
runtime and source/runner guards. Gate PR8's separate fixed-pilot files are untouched.
The older dirty permissions worktree has the same two `contents: read` ceilings
already in main; those bytes and its ownership remain preserved.

The supplied QA caller still pins `v0.4.11`; that immutable workflow does not adopt
this candidate. Current main's control fixture is also newer than the older
caller's `v0.4.0` manifest. This proposal preserves each existing pin. A reviewed
immutable workflow release and separately reviewed QA caller adoption are still
required. No Actions execution, release or production equivalence is claimed.

For QA only, hosted setup selects Python3.12. The existing Mac route requires
`/opt/homebrew/opt/python@3.12/libexec/bin/python3`, checks the exact minor version,
and places that directory on the job's temporary PATH. Missing/wrong runtime
fails before the compliance command; it never falls back or installs on the Mac.
The existing generic Mac readiness check and all other caller profiles remain.

QA Kit's owned `bin/qa_selfcheck.sh` now enforces Python3.12 and includes the
stdlib check after docs, standards and unit tests. Task retains its Python
precondition and invokes that complete entrypoint once. This makes the old
manifest's selfcheck command include all those assertions when explicitly supplied
with the right runtime. It intentionally fails under the older caller's wrong
runtime until adoption is separately qualified; no old green result is rewritten.

Successful child output remains suppressed by the unchanged pinned checker.
An explicit task-local report destination records actual interpreter version and
binary digest, exact candidate/entrypoint hash, physical tracked source identity,
cleanliness, selected check statuses and exit
code. It copies no raw child output or executable path. The workflow's separate
summary binds that report to caller/checker/control commits and rechecks the
candidate/entrypoint identity. Missing or incompatible provenance is explicit and
fails the reporting step. Validation uses explicit conditions so Python
optimization cannot disable it. A zero exit with failed/blocked checks is
incompatible; a genuine nonzero exit with failed/blocked checks remains
reportable failure evidence. A failure remains a failure; summary data is not a
replacement compliance receipt or security acceptance.

Offline tests exercise missing/wrong interpreters, real failing unit/stdlib
fixtures, successful provenance, unavailable/tampered reporting, immutable pins,
existing permissions and unchanged non-QA workflow bytes. Actual hosted/Mac events
and exact-candidate adopted release evidence remain unrun. The QA runtime tests
use temporary directories, synthetic scripts and no installs or model calls.
