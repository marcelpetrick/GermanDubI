# Deep review

A review of GermanDubI as it stands at `6052417`: 15,235 lines of backend, 6,120 of backend
tests, 4,130 of frontend, 713 of documentation. Twenty findings, each with what is wrong,
why it matters, and enough detail to act on without rediscovering it.

Severity is about consequence, not effort:

- **High** — can lose data, corrupt state, or mislead a user into believing something false.
- **Medium** — will cost real time or produce wrong results under conditions that will occur.
- **Low** — worth doing, costs little, and nothing breaks meanwhile.

What is deliberately *not* listed: the layering is clean and enforced by executable tests,
the domain has no infrastructure imports, path traversal is guarded at both file-serving
boundaries, no secrets reach logs, and provenance is recorded on every artifact. Those are
in good shape and the review found nothing to say about them.

---

## Correctness and data safety

* [ ] **[High] The schema is created two different ways, and only one of them is used.**
  `composition.py:115` calls `database.create_all()`, while `backend/src/germandubi/infrastructure/db/migrations/` holds Alembic migrations that nothing runs automatically. A fresh install gets its schema from SQLAlchemy metadata and is never stamped, so `alembic upgrade head` on it fails with "table already exists"; an existing install never receives new columns at all. This was hit for real when `projects.voice` was added — the fix required `alembic stamp` followed by `upgrade`, which no user would guess.
  *Do:* pick one owner of the schema. The straightforward option is to run migrations at startup (`alembic upgrade head` against the configured URL) and delete `create_all`, stamping existing databases once on first run by detecting the `projects` table without an `alembic_version` row. Add a test that creates a database at the previous revision and upgrades it.

* [ ] **[High] `checkpoint()` now commits, and no handler documents that it must tolerate this.**
  Committing mid-stage is what keeps the write lock short (`worker/context.py`), but it also means a stage that fails halfway leaves partial results behind. The synthesis handler happens to cope, because it skips segments that already have output; nothing states that as a requirement, and the next handler written will not know it.
  *Do:* state the contract in `StageContext.checkpoint`'s docstring and in `AGENTS.md` section 7 — *a handler must be safe to re-run after partial completion*. Then add a test that runs a handler, kills it after a checkpoint, re-runs it, and asserts the result equals an uninterrupted run.

* [ ] **[High] A stage that exceeds its lease can be claimed by a second worker while still running.**
  `job_lease_seconds` defaults to 900. Separation measured 2.38x realtime on CPU over a 120-second sample, which puts a 40-minute source in the same order of magnitude as the lease itself. `claim_next` reclaims expired leases, so a second worker process (nothing prevents starting one) could pick up a job the first is still executing, and both would write to the same workspace.
  *Do:* renew the lease from the stage's checkpoint, which already runs periodically, rather than setting it once at claim time. Failing that, refuse to start a second worker by taking an advisory lock on the data directory, and say so in the error.

* [ ] **[Medium] `delete_all` deletes every workspace inside a single transaction.**
  `projects.py` pages through projects and calls `uow.store.delete_workspace` for each, all within one unit of work. Filesystem deletion is not transactional: if the transaction rolls back after several directories are gone, the database still lists projects whose files no longer exist.
  *Do:* commit the database deletion first, then remove directories, and make workspace removal idempotent so a crash between the two is recoverable. Alternatively record intent in a table and sweep orphaned directories on startup.

* [ ] **[Medium] Stage retries have no backoff.**
  `_finish_failed` re-queues immediately, so a deterministic failure burns all three attempts in milliseconds and a transient one — a rate-limited download, a busy GPU — retries at the least useful possible moment. The yt-dlp investigation in this repository is a live example: three immediate attempts all failed while the same command succeeded a minute later.
  *Do:* store `next_attempt_at` on the job and have `claim_next` skip jobs whose time has not come. Exponential from a few seconds is enough; the point is that attempt two is not simultaneous with attempt one.

## Architecture

* [ ] **[Medium] `repositories.py` is 1,135 lines holding four repositories and their mappers.**
  Every persistence concern in the application lives in one file: project, segment, artifact and job repositories, plus roughly a dozen row/domain mapping functions between them. Nothing is wrong with the code, but a file this size is where merge conflicts concentrate and where a reader stops being able to hold the whole thing in their head.
  *Do:* split by aggregate into `repositories/projects.py`, `segments.py`, `artifacts.py`, `jobs.py`, keeping the mapping functions next to the repository that owns them, and re-export from `repositories/__init__.py` so no import site changes.

* [ ] **[Medium] Provider settings are cross-wired through `transcription_provider`.**
  `ProviderRegistry.probe()` and `prosody()` both check `settings.transcription_provider == "fake"`, so selecting a fake transcript provider silently changes two unrelated ports. It works, and the deterministic E2E depends on it, but the coupling is invisible from the setting's name and will surprise whoever changes it next.
  *Do:* give each port its own setting (`probe_provider`, `prosody_provider`) defaulting to `auto`, and have `scripts/e2e-server` set them explicitly. Alternatively introduce one `deterministic_providers` flag that means what the E2E actually wants.

* [ ] **[Medium] No ADR records the concurrency and transaction model.**
  The rule that a stage runs outside any open write transaction is now load-bearing — it is the difference between a working application and `database is locked` — and it lives only in a commit message and a section of `c4.md`. ADRs exist for smaller decisions (a separate worker, SSE over WebSocket).
  *Do:* write `docs/adr/0012-short-transactions-around-stages.md` covering the decision, the rejected alternative (a second connection for progress, which deadlocks), and the consequence that handlers must be resumable. The material is in `c4.md` already; it needs the ADR's status and context framing.

## Testing

* [ ] **[High] The real-provider tests are marked, excluded by default, and run nowhere.**
  `pytest.ini_options` deselects `-m real_provider`, `make test-real` exists, and no workflow or script ever calls it. Three tests carry the marker, so the only automated check that a real model produces anything at all is `scripts/benchmark_real_dub.py`, which is also run by hand. Every gate in the repository passes against fakes.
  *Do:* add a scheduled workflow (weekly is enough) that installs the provider extras and runs `make test-real`, allowed to fail without blocking `main`. It will catch upstream breakage — exactly the class of failure the yt-dlp incident was — before a user does.

* [ ] **[Medium] The frontend has no coverage measurement and roughly a third of its components have tests.**
  Five test files cover fourteen components. The backend enforces 95.1% and the frontend enforces nothing, so the untested half is invisible rather than merely untested. `HelpPage`, `AboutPage`, `VoicePicker`, `PipelineProgress` and `SegmentWorkspace` have no direct tests.
  *Do:* enable `vitest --coverage` with a floor that reflects today's reality and raise it deliberately. Prioritise `VoicePicker` (network, audio playback, error path) and `SegmentWorkspace` (filtering, selection following the filter), which have real logic rather than markup.

* [ ] **[Medium] There is no error boundary; a render error blanks the page.**
  `grep -rn Boundary frontend/src` returns nothing. Any exception thrown during render unmounts the whole tree, leaving a white page with the explanation only in the console — where a non-developer will never look.
  *Do:* wrap the routes in an error boundary that shows what failed, offers a reload, and links to the About page for the version to report. React Router's `errorElement` covers route-level failures; a class boundary is still needed for render errors elsewhere.

* [ ] **[Medium] The browser tests cover the happy path only.**
  Both specs drive a successful dub. Nothing exercises a failed stage, a degraded environment, an unavailable source, or a project stopped mid-run — and those are the paths where the interface has the most to say and the most to get wrong.
  *Do:* add specs for a failed stage (force one by pointing at an unusable fixture) and for the degraded-environment banner, asserting the interface explains the failure rather than showing a spinner forever.

* [ ] **[Low] No automated accessibility check, despite deliberate accessibility work.**
  There are 34 `aria-`/`role` attributes, a skip link, a `forced-colors` fallback and focus-visible styling — the intent is clearly there, and nothing verifies it. Contrast in particular is a real risk given a neon palette that was tuned by eye.
  *Do:* add `@axe-core/playwright` and assert no violations on the home, project, help and about pages, in both themes. It is roughly ten lines and it protects work already done.

## Operations and supply chain

* [ ] **[High] Nothing scans dependencies for known vulnerabilities.**
  Neither workflow runs `pip-audit`, `osv-scanner`, or npm's audit, and the project pulls a large transitive surface — torch, spacy, stanza, onnxruntime and their dependencies. A GPL-licensed local tool still ships code that parses untrusted media.
  *Do:* add `uv run pip-audit` and `pnpm audit --audit-level=high` to CI as a separate non-blocking job first, then make it blocking once the baseline is clean. Dependabot or Renovate would also close the gap between "pinned" and "pinned and maintained".

* [ ] **[Medium] Released artifacts carry no provenance or signature.**
  `release.yml` builds a wheel and an sdist and uploads them. Anyone downloading has no way to verify they came from this repository and this commit, which matters more for a GPL tool people are invited to self-host.
  *Do:* add `actions/attest-build-provenance` after the build step and publish the attestation with the release. It needs `id-token: write` and about five lines.

* [ ] **[Medium] The gate silently removes the providers needed to use the product.**
  `uv sync --locked` in `localPipeline.sh` uninstalls the optional extras every run, so the sequence "run the gate, then dub something" leaves a machine that cannot dub. It is documented in three places, which is itself the evidence that it surprises people — it caught this project's own maintainer twice during development.
  *Do:* have the pipeline detect that the extras were present before the sync and restore them at the end, or print a closing line naming `make install-providers` when it removed them. The gate should not leave the machine less capable than it found it.

* [ ] **[Low] The wheel smoke test only checks that the CLI reports a version.**
  `release.yml` installs the built wheel and runs `germandubi version`. That proves the package imports and the entry point is wired; it would not catch a missing template, an unpackaged migration, or a broken static bundle.
  *Do:* extend it to `germandubi doctor` and a request against `germandubi serve` for `/api/v1/health`, which exercises packaging, configuration and the API together. `localPipeline.sh` already does the serve check and the code can be shared.

## Interface

* [ ] **[Medium] Translation is half finished, and nothing detects the half that is missing.**
  `SegmentEditor` and `ErrorAlert` contain no `useT` at all, and `ProjectPage` still has hardcoded English — "Loading project…", "German preview", "The export includes German and original audio tracks." A reader who selects Croatian gets a mixture, which is worse than English throughout because it looks broken rather than untranslated.
  *Do:* finish the two components and the remaining `ProjectPage` strings, then add a lint rule (`eslint-plugin-i18next` or a custom rule) that fails on literal text in JSX so the next English string cannot be added silently.

* [ ] **[Low] Voice previews cannot be stopped once started.**
  `VoicePicker` creates an `Audio` element, disables the button while it plays, and offers no way to stop it. A voice sample is short, so this is a small annoyance rather than a fault — but selecting a different voice while one is playing leaves the previous sample playing over the new selection.
  *Do:* turn the button into play/stop, pause the current audio on unmount and on voice change, and keep the element in a ref rather than creating a new one per press.

* [ ] **[Low] Queue position is invisible while a second project waits.**
  Source inspection is prioritised so a newly added URL is analysed quickly, but once a dub is running the second project's own dub waits behind roughly fifteen stages with nothing on screen explaining the wait. The interface shows a project that is "ready" and apparently idle.
  *Do:* expose the queued job count and position from the pipeline service and show "waiting for another project to finish" with the position. The data is already in the jobs table; only the endpoint and the label are missing.

---

## Suggested order

The first three High findings are the ones that can produce wrong state rather than
inconvenience: schema ownership, the resumability contract, and the lease. The dependency
scan is High for a different reason — it is the only finding here that someone outside this
repository could exploit, and it is an afternoon's work.

Nothing in this list is urgent enough to hold a release. The application works, the gate is
honest, and every finding above is a known gap rather than a surprise.
