# GermanDubI completion plan

This document is the committed execution ledger for bringing the first public release to
a safe, reproducible state. Every completed step is marked in the same atomic commit as
the work it records. The repository is prepared locally; publishing and pushing remain
the maintainer's responsibility.

Status values: `PENDING` · `IN PROGRESS` · `COMPLETE`.

## 1. Audit the inherited implementation · `COMPLETE`

- Compared the implementation with `vision.md`, `AGENTS.md`, the C4 documentation, and
  the executable architecture constraints.
- Exercised backend, frontend, browser E2E, packaging, and provider fallback paths.
- Recorded remaining work below rather than silently expanding or dropping scope.

Evidence: commits `a8d5809`, `2f7790c`, and the subsequent focused fixes.

## 2. Establish GPLv3-or-later licensing and ownership · `COMPLETE`

- Replaced MIT references with the complete GPLv3 license text and SPDX metadata.
- Identified Marcel Petrick (`mail@marcelpetrick.it`) as the author and welcomed
  contributions.
- Aligned package, API, README, contribution, ADR, question, and changelog metadata.

Evidence: commit `a58a146`.

## 3. Pin and update the supported dependency toolchain · `COMPLETE`

- Checked direct dependencies against their authoritative registries and pinned exact
  compatible versions.
- Locked Python, Node.js, pnpm, frontend, E2E, and optional-provider dependencies.
- Verified the complete build and deterministic E2E flow on the supported toolchain.

Evidence: commit `43272ad`.

## 4. Correct defects exposed by the audit · `COMPLETE`

- Kept long unpunctuated speech segments within the configured size at word boundaries.
- Prevented generic downloader failures from being mislabeled as age restrictions.
- Covered both regressions with focused tests.

Evidence: commit `faba5fc`.

## 5. Enforce more than 95% backend line coverage · `COMPLETE`

- Exercise meaningful application, provider, process, worker, version, and API boundary
  behavior rather than adding assertion-free coverage fillers.
- Set an enforced backend line-coverage floor above 95% while keeping real providers
  opt-in and default CI deterministic.
- Acceptance: formatting, lint, strict typing, and the complete backend suite pass with
  measured coverage above the configured threshold.

Evidence: 732 deterministic tests passed with 95.19% line coverage; formatting, Ruff, and
strict mypy checks passed.

## 6. Repair the real-source probe · `COMPLETE`

- Diagnosed a real 40-minute source failing to analyze with "the source site returned
  metadata this version cannot read": captured process output was capped at 256 KB, which
  truncated the downloader's ~640 KB JSON metadata and misattributed a local limit to the
  source.
- Made the capture limit a per-call decision, raised it for the two callers that parse
  stdout as JSON, and made truncation reported rather than silent.
- Acceptance: the failing URL probes successfully through the application's own code path.

Evidence: commit `22d4ffc`.

## 7. Add a from-scratch local quality pipeline · `COMPLETE`

- Added an executable `localPipeline.sh` as the single local/CI entry point, reachable as
  `make pipeline`.
- It validates prerequisites and pinned runtimes, performs locked setup, runs every
  quality gate and build, installs the deterministic browser, executes E2E, and
  smoke-tests the production server, tearing the server down on every exit path.
- Fixed three defects the first real run exposed: Playwright's generated output failed the
  Prettier gate, the Node version pinned in `.node-version` was neither enforced by the
  gate nor stated correctly in the README, and the browser install demanded a sudo
  password on a developer machine.
- Acceptance: passes from a clean checkout in 136 s using only documented prerequisites.

Evidence: commit recorded with this step.

## 8. Align GitHub quality and public-release automation · `COMPLETE`

- CI now calls `./localPipeline.sh` instead of restating its steps, so the developer gate
  and the CI gate cannot drift; both read the Node version from `.node-version`.
- Added least-privilege, concurrency-safe release automation triggered by an annotated
  semantic-version tag. It reruns the whole pipeline, refuses to publish when the tag does
  not match the built version or the changelog has no section for it, verifies the wheel
  installs and runs, and publishes both artifacts with notes extracted from the changelog.
- Added CI, release, coverage, Python, and GPL badges to the README.
- Acceptance: both workflows parse, and the changelog extraction and version guards were
  exercised against fixtures covering the match, absent, and boundary cases.

Evidence: commit recorded with this step.

## 9. Reconcile C4, setup, operations, and release documentation · `COMPLETE`

- Compared every documented boundary and runtime path with the implementation and
  corrected three places where the documentation described something the code did not do:
  ADR-0010 claimed automatic selection never picks a network provider, while source
  acquisition always has and must; the C4 view did not mention that probe selection depends
  on the source kind; and the setup guide named a Node version the test stack cannot run on.
- Documented the local pipeline, the optional real-provider limitations and how the gate
  removes them again, release creation, and troubleshooting.
- Acceptance: no documented behavior now contradicts the implementation.

Evidence: commit recorded with this step.

## 10. Verify and time a real end-to-end dub · `COMPLETE`

- Add committed, re-runnable automation that takes a real YouTube source through the whole
  product path: download, analyze, transcribe, translate, synthesize German speech, mix,
  and produce a playable video carrying the German audio.
- Measure and report wall-clock time per pipeline stage and as a ratio of source duration,
  writing a machine-readable result next to a human-readable summary.
- Use `https://www.youtube.com/watch?v=f3r05guSo1w` (40 min, English, auto-captions) as
  the reference source, with a bounded-excerpt mode so the run is practical to repeat.
- Acceptance met. The complete 40-minute reference source dubs end to end in 492 s, a
  0.21x realtime factor, producing a 754 MB MKV with a German audio track, the original
  English kept as a second track, and German and English subtitles. Speech recognition,
  Argos and Piper all really ran; the transcript provider is read back from the persisted
  artifact rather than from what the registry would have chosen.
- Getting there required fixing four defects that only a real, full-length source exposed:
  segmentation rejected ordinary recognizer output, estimated word timing escaped its cue,
  automatic captions were mistaken for manual ones, and the mix stage built an FFmpeg
  expression too large to evaluate.

Evidence: `docs/benchmarks/real-dub.json`, `docs/benchmarks/real-dub-full.json`.

## 11. Perform clean-install and live release-candidate verification · `COMPLETE`

- Ran the full pipeline from clean generated state: eleven stages green in 143 s.
- Verified the built wheel installs into a fresh environment and its CLI runs.
- Found and fixed one flaw while doing so: the release workflow verified the wheel using
  the runner's default `python`, which can sit outside the supported range and would have
  failed a release for a reason unrelated to the release. It now uses the pinned
  interpreter via `uv`.
- Acceptance: all gates green, no untracked generated output, worktree clean.

Evidence: commit recorded with this step.

## 12. Review architecture, code, practice, and documentation · `COMPLETE`

Reviewed in order: architecture against its constraints and ADRs, the implementation
against best practice, then every document against the code.

Severe findings, all fixed:

1. **Local files could not be dubbed at all.** Probe selection ignored the source kind and
   always returned the downloader, which refuses a local file. Fixed by adding a local
   probe and dispatching on source kind (`d2b8e3c`).
2. **Word ordering rejected ordinary recognizer output.** The invariant checked for overlap
   while claiming to check order, failing long real sources (`963fa77`).
3. **Filled-in word timing escaped its cue**, corrupting order across cue boundaries and
   failing a real 40-minute source (`229d3bd`).
4. **Automatic captions were treated as manual**, so the pipeline preferred unpunctuated
   text over installed speech recognition and silently produced worse German (`3923989`).
5. **Production code lived in `fakes.py`.** The only alignment provider was called
   `FakeAlignmentProvider` and was reported to users as "Fake alignment"; the bug in
   finding 3 hid there behind that name (`483f1d2`).
6. **A half-present optional package crashed instead of degrading** (`2e9e837`).

Also fixed: `germandubi doctor` omitted two selectable providers (`20536cd`); two tests
passed only because the machine happened not to have the optional extras installed.

Accepted, not fixed, and deliberately recorded:

- **Provider settings are cross-wired.** `probe()` and `prosody()` key off
  `transcription_provider == "fake"`, so selecting a fake transcript provider silently
  changes two other ports. It is how the deterministic E2E run selects fakes, and it works,
  but each port should have its own setting. Not fixed here: adding configuration surface
  immediately before a release is more risk than the confusion costs.
- **Stage retries have no backoff.** A failed stage retries twice, immediately. For a
  deterministic failure that is three identical failures in a row; for a transient network
  error, immediate retry is the least useful moment to try again.

Acceptance: the full gate is green, `doctor` reports every provider, and the real
end-to-end dub of step 10 still produces a playable German-dubbed file.

Evidence: the commits named above.

## 13. Finalize the local v0.1.0 release state · `PENDING`

- Move release notes out of `Unreleased`, verify the exact SCM-derived version, and make
  the final release-readiness commit.
- Create an annotated local `v0.1.0` tag only on the fully green commit.
- Do not push. When the maintainer force-pushes the commits and tag, the tag workflow will
  create the public GitHub release.
