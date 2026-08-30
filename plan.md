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

## 5. Enforce more than 95% backend line coverage · `IN PROGRESS`

- Exercise meaningful application, provider, process, worker, version, and API boundary
  behavior rather than adding assertion-free coverage fillers.
- Set an enforced backend line-coverage floor above 95% while keeping real providers
  opt-in and default CI deterministic.
- Acceptance: formatting, lint, strict typing, and the complete backend suite pass with
  measured coverage above the configured threshold.

## 6. Add a from-scratch local quality pipeline · `PENDING`

- Add an executable `localPipeline.sh` as the single local/CI entry point.
- Validate prerequisites and pinned runtimes, perform locked setup, run every quality
  gate and build, install the deterministic browser, execute E2E, and smoke-test the
  production server with cleanup on every exit path.
- Acceptance: it succeeds from a clean checkout using only documented prerequisites.

## 7. Align GitHub quality and public-release automation · `PENDING`

- Make GitHub Actions call the local pipeline so CI cannot drift from developer checks.
- Add least-privilege, concurrency-safe release automation triggered by an annotated
  semantic-version tag; validate version and changelog, rebuild, and publish verified
  artifacts as a public GitHub release.
- Add truthful quality, release, coverage, runtime, and GPL badges to the README.

## 8. Reconcile C4, setup, operations, and release documentation · `PENDING`

- Compare every documented boundary and runtime path with the implemented composition
  roots, provider behavior, persistence, and trust boundaries.
- Document clean setup, local pipeline use, development and production startup, optional
  real-provider limitations, troubleshooting, release creation, and contribution flow.
- Resolve or record any newly discovered expensive decision in `questions.md`/ADRs.

## 9. Perform clean-install and live release-candidate verification · `PENDING`

- Run the full local pipeline from clean generated state.
- Verify backend, frontend, deterministic provider workflow, browser E2E, production
  static serving, package contents, CLI/API versions, licensing, and release artifacts.
- Acceptance: all gates are green, no untracked generated output remains, and the worktree
  contains only intentional committed changes.

## 10. Finalize the local v0.1.0 release state · `PENDING`

- Move release notes out of `Unreleased`, verify the exact SCM-derived version, and make
  the final release-readiness commit.
- Create an annotated local `v0.1.0` tag only on the fully green commit.
- Do not push. When the maintainer force-pushes the commits and tag, the tag workflow will
  create the public GitHub release.
