# Contributing to GermanDubI

Contributions are welcome. Please open a focused issue or pull request, or contact Marcel
Petrick at <mail@marcelpetrick.it> when a change needs design discussion first. By
contributing, you agree that your contribution is provided under the repository's
[`GPL-3.0-or-later`](LICENSE) license.

## Setup

```bash
corepack enable pnpm
make install            # locked backend, frontend and e2e dependencies
make hooks              # pre-commit
./localPipeline.sh      # the full gate, once, to confirm the environment
```

The pinned runtimes are in `.python-version` and `.node-version`; an older Node produces a
frontend test suite that fails to load rather than a clear version error, so use the pin.

## The rules that matter

1. **Small, atomic, conventional commits.** One coherent change per commit, message in
   [Conventional Commits](https://www.conventionalcommits.org/) style
   (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `build:`, `ci:`, `chore:`).
2. **Never hand-edit a version.** Versions are derived from Git tags by `setuptools-scm`.
   A release is an annotated tag (`v0.3.0`); every other commit gets a development version
   automatically.
3. **Respect the layer boundaries.** `domain` imports nothing from FastAPI, SQLAlchemy,
   `yt-dlp` or FFmpeg. `application` depends on ports, not on provider implementations.
   These rules are enforced by tests in `backend/tests/unit/test_architecture.py`.
4. **All external processes go through the process runner.** No bare `subprocess` calls
   in `backend/src`; an architecture test enforces it. Operator scripts under `scripts/`
   drive the application from outside and are exempt.
5. **The gate must pass before you push.** `make check` is the fast inner loop;
   `./localPipeline.sh` is the complete gate and is exactly what CI runs, so a green run
   locally means a green run there.

## Definition of Done

See §61 of [`docs/product/vision.md`](docs/product/vision.md). In short: implementation, type annotations, public
docstrings, tests at the right level, migration if persistence changed, docs and ADR
updated if architecture changed, changelog entry if the behaviour is release-relevant.

## Open design questions

Unresolved architecture and design decisions are tracked in [`docs/project/questions.md`](docs/project/questions.md).
When you resolve one, update that file and write an ADR in `docs/adr/`.
