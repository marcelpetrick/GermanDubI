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

## 9. Reconcile C4, setup, operations, and release documentation · `PENDING`

- Compare every documented boundary and runtime path with the implemented composition
  roots, provider behavior, persistence, and trust boundaries.
- Document clean setup, local pipeline use, development and production startup, optional
  real-provider limitations, troubleshooting, release creation, and contribution flow.
- Resolve or record any newly discovered expensive decision in `questions.md`/ADRs.

## 10. Verify and time a real end-to-end dub · `IN PROGRESS`

- Add committed, re-runnable automation that takes a real YouTube source through the whole
  product path: download, analyze, transcribe, translate, synthesize German speech, mix,
  and produce a playable video carrying the German audio.
- Measure and report wall-clock time per pipeline stage and as a ratio of source duration,
  writing a machine-readable result next to a human-readable summary.
- Use `https://www.youtube.com/watch?v=f3r05guSo1w` (40 min, English, auto-captions) as
  the reference source, with a bounded-excerpt mode so the run is practical to repeat.
- Acceptance: a real German-dubbed output file exists and plays, with a recorded timing
  breakdown committed alongside the automation.

## 11. Perform clean-install and live release-candidate verification · `PENDING`

- Run the full local pipeline from clean generated state.
- Verify backend, frontend, deterministic provider workflow, browser E2E, production
  static serving, package contents, CLI/API versions, licensing, and release artifacts.
- Acceptance: all gates are green, no untracked generated output remains, and the worktree
  contains only intentional committed changes.

## 12. Review architecture, code, practice, and documentation · `PENDING`

- Review, step by step and in this order: the architecture against its own constraints and
  ADRs; the implementation against software best practice; and every document against what
  the code actually does.
- Fix every finding rated severe or critical. Record accepted lower-severity findings
  rather than silently leaving them.
- Acceptance: the full gate stays green, the real end-to-end dub of step 10 still
  produces a playable German-dubbed file, and no severe or critical finding is open.

## 13. Finalize the local v0.1.0 release state · `PENDING`

- Move release notes out of `Unreleased`, verify the exact SCM-derived version, and make
  the final release-readiness commit.
- Create an annotated local `v0.1.0` tag only on the fully green commit.
- Do not push. When the maintainer force-pushes the commits and tag, the tag workflow will
  create the public GitHub release.
