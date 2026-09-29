# Gate validation adapter v1

`bin/validation_adapter.py` is an additive bridge to QA Kit's shared validation
protocol 1.0. It executes only explicitly enrolled repositories. The existing
`compliance.yml`, its checker/fixture pins, and protected canonical
profiles remain separate. Installing this adapter does not enroll a repository.
The initial publication workflow supplies qa-kit `v0.7.0` only to Agency's
unenrolled legacy cohort, allowing its reviewed setup to prepare the public QA
fixture for adapter qualification. Every other legacy caller retains `v0.6.6`.
Agency's legacy checker, full manifest coverage, runner guards and check identity
remain required; this bootstrap is independent of later enrollment bundles.

QA owns task planning, typed environment values, runtime/variant validation,
prerequisite blocking, timeouts and source/fixture checks. Gate invokes the exact
shared CLI instead of implementing those semantics again. Repository owners keep
their test bodies. Agency owns release evidence acceptance.

## Trusted inputs and source

The invoking workflow supplies fixed reviewed control paths and immutable commit
and digest pins. Candidate code does not supply runner authorization. The adapter
checks the control checkout's exact commit, cleanliness, hidden index flags,
physical Git blob equality and executable modes before reading control JSON.
Symlinks and path traversal are refused. Registry and authorization digests must
match the independently pinned bundle. The executor and Gate implementation are
independently verified against their bundle commits before loading their code.
Control sources are verified again after execution.

The wrapper supplies only `PATH`, `LANG`, `LC_ALL` and `TZ` to the isolated shared
interpreter. It has a 30-minute aggregate deadline for the initial cohort. On
cancellation or deadline it forwards termination to the executor, allowing up to
15 seconds for QA's task-group cleanup before stopping an unresponsive executor.
QA continues to own each task's timeout and prerequisite outcomes.

Each central registry row binds its repository name to an exact GitHub repository
and required CI selection. A caller cannot choose another repository or weaker
selection. Empty/malformed/missing enrollment fails this adapter; it never
silently reports a legacy pass. Routing unenrolled callers to legacy execution is
the separately reviewed workflow's responsibility.

CI authorization supports disposable GitHub-hosted `push` and `pull_request`
contexts plus the separately qualified, inactive Mac pilot policy below.
The actual event payload must agree with the repository,
ref and expected candidate SHA. PR heads, including hosted fork PRs, are checked
directly; a merge SHA cannot substitute. `pull_request_target`, schedules,
dispatch events and every other self-hosted route are unsupported. The existing agents
and BeanMind profiles are explicitly excluded from this adapter.

The inactive Mac policy accepts `push` to `refs/heads/main` only for
`stevekkall-beansgc/legume-labs` on runner
`beans-macbook-legume-labs-validation`, variant `macos-arm64-py312`, or
`stevekkall-beansgc/beanfit-app` on runner
`beans-macbook-beanfit-app-validation`, variant `macos-arm64-node22-py312`.
Both require Actions self-hosted/macOS/ARM64 metadata, the actual event payload
and exact source SHA, and a complete centrally reviewed `ci-required` selection
in context `ci`. Runner labels alone confer no authority. This source release
does not register runners or enroll either repository. The later workflow must
apply the same trusted guard before candidate checkout, and independent actual
GitHub job/readback must prove the repository-scoped runner and exact candidate.
Private/fork PRs never select this persistent-machine route. Existing Linux tasks
and any normative Linux coverage remain separately recorded; Mac is not a Linux
cell or a release-context substitute.

The existing README/AGENTS/manifest-unit-command documentation check remains
required alongside shared execution. A passing task plan cannot conceal its
failure. A future central docs task needs explicit equivalence qualification.

## Invocation

Prepared trusted paths are separate from the candidate checkout. The result
artifact must be new and outside candidate and control sources.

```sh
python3 -I /pinned/gate-kit/bin/validation_adapter.py \
  --root /candidate --repo sample --qa-root /pinned/qa-executor \
  --controls-root /pinned/qa-controls --controls-commit CONTROL_SHA \
  --registry validation/registry.json \
  --bundle validation/bundles/sample.json --expected-bundle BUNDLE_SHA256 \
  --authorization validation/authorizations/sample.json \
  --variant linux-py312 --expected-head CANDIDATE_SHA \
  --context ci --output /scratch/new-validation-result.json
```

Add `--fixture NAME=/pinned/fixture` only for fixtures required by the plan.
`--context local` runs a local comparison with the same pinned controls; it does
not grant CI authority. CI uses the centrally fixed selection. A local comparison
may explicitly select another registered selection, and its scope is reported.

The workflow supplies `GATE_EVENT_NAME`, `GATE_REPOSITORY`,
`GATE_EVENT_REPOSITORY`, `GATE_EXPECTED_SHA`, `GATE_REF`, and `GATE_PUSH_AFTER`.
The adapter reads GitHub's event file and hosted runner/run metadata. It emits
one final JSON verdict retaining `gate: compliance`, `failures`, `repos` and
per-check documentation/validation outcomes, with the shared detailed receipt.
Exit zero requires passing docs and a passing **complete** required selection.
An individual passing variant with remaining required cells is not green.

## Evidence limits and integration

`github_check_verified` is always false in a local execution receipt. Context and
run identifiers describe execution; actual GitHub dispatch, check identity and
conclusion must be independently read back. A receipt cannot manufacture a
successful check. Existing external check names remain `compliance / compliance`;
the separately published workflow must preserve them.

`bin/check_parity.py --local LOCAL_ENVELOPE --ci CI_ENVELOPE --repo REPO
--head CANDIDATE_SHA --bundle BUNDLE_SHA256` compares two Gate verdicts from the
same qualified host. Both must pass the complete required selection and preserve
the exact candidate, executor, adapter, controls, fixtures, runtime observations,
plan digests and task outcomes. The comparison always reports
`github_check_verified: false`. Executing the local command on hosted Linux can
qualify command-versus-adapter parity there; it does not establish macOS/Linux
equivalence or provide the independent GitHub check readback.

The shared executor is not an OS/network sandbox. Effects declarations require
trusted contract and repository review plus runner isolation. Initial profiles
do not authorize private data, knowledge mutation, live providers, deployment,
new schedulers, billing changes or system license acceptance.

The supported rollout publishes the empty-registry QA executor, then Gate/Agency
adapters, then a later control commit pinning those earlier immutable sources.
Only afterward does a qualified reusable workflow/caller opt in. This avoids
self-referential bundle pins. Retain prior workflows and required coverage for
rollback; unavailable CI or missing variants never justify weakening checks.

## Qualification

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_stdlib.py bin/
bash setup/qa-validation/bootstrap.sh
bash scripts/test_validation_e2e.sh
```

The explicit integration suite uses real shared executor bytes from the prepared
QA fixture and disposable synthetic Git repositories. Its default fixture path is
`.qa-fixtures/qa-kit`; a missing fixture fails, with no sibling fallback or skip.
The owned bootstrap fetches only the reviewed public QA repository at exact
commit `cf3cebee5a4f975260c330aa585b7cd3d5b63a79`, verifies all tracked physical
source and executor digest, and refuses an existing dirty/drifted fixture without
resetting or deleting it. It never invokes QA's tests or tasks. An explicitly
prepared fixture can be supplied with `GATE_SHARED_QA_FIXTURE`; the default needs
no exported setup variable. QA owns registration of these setup/E2E entrypoints.
Tests cover successful delegation, typed literal environment, setup failure
blocking dependents, retained docs failure, incomplete variants, bad bundle
digests, hidden control edits, cancellation cleanup, same-host local/CI comparison
and artifact overwrite prevention. Synthetic success
does not establish product or fleet acceptance.
