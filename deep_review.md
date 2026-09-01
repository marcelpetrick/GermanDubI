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

* [x] **[High] The schema is created two different ways, and only one of them is used.** — *Fixed.*
  `composition.py:115` calls `database.create_all()`, while `backend/src/germandubi/infrastructure/db/migrations/` holds Alembic migrations that nothing runs automatically. A fresh install gets its schema from SQLAlchemy metadata and is never stamped, so `alembic upgrade head` on it fails with "table already exists"; an existing install never receives new columns at all. This was hit for real when `projects.voice` was added — the fix required `alembic stamp` followed by `upgrade`, which no user would guess.
  *Done:* migrations are the only owner. `Database.migrate()` runs `upgrade head` against the database being opened, and startup calls it instead of `create_all`. A database that predates Alembic is stamped at the base revision and upgraded, which is safe because each migration now checks whether its change is already present. `create_all` survives for tests that want a schema in 5 ms rather than 78 ms, and a drift test asserts the two produce identical columns so they cannot diverge again. Migrations no longer reconfigure the application's logging.

* [x] **[High] `checkpoint()` now commits, and no handler documents that it must tolerate this.** — *Fixed.*
  Committing mid-stage is what keeps the write lock short (`worker/context.py`), but it also means a stage that fails halfway leaves partial results behind. The synthesis handler happens to cope, because it skips segments that already have output; nothing states that as a requirement, and the next handler written will not know it.
  *Done:* the contract is stated where a handler author will meet it -- in `StageContext.checkpoint`'s docstring and in `AGENTS.md` section 7 -- together with the pattern that satisfies it and what goes wrong without it. Two tests enforce it: one asserts that work committed before a failure survives, and one runs a resumable handler that fails half-way and asserts the retry produces exactly the uninterrupted result, neither redoing nor skipping.

* [x] **[High] A stage that exceeds its lease can be claimed by a second worker while still running.** — *Fixed.*
  `job_lease_seconds` defaults to 900. Separation measured 2.38x realtime on CPU over a 120-second sample, which puts a 40-minute source in the same order of magnitude as the lease itself. `claim_next` reclaims expired leases, so a second worker process (nothing prevents starting one) could pick up a job the first is still executing, and both would write to the same workspace.
  *Done:* both, because neither alone is sufficient. The lease is renewed from the stage's checkpoint, so a stage that legitimately runs longer than its lease is no longer mistaken for an abandoned one -- but a stage inside a single long subprocess has no checkpoint to renew from, so that could not be the whole answer. `Worker.exclusive()` takes an exclusive `flock` on the data directory and `germandubi worker` refuses to start when another holds it, naming the directory. The lock is released by the operating system on exit, so a crashed worker does not lock its successor out.

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

* [x] **[Medium] No ADR records the concurrency and transaction model.** — *Fixed.*
  The rule that a stage runs outside any open write transaction is now load-bearing — it is the difference between a working application and `database is locked` — and it lives only in a commit message and a section of `c4.md`. ADRs exist for smaller decisions (a separate worker, SSE over WebSocket).
  *Done:* written, and it earned its place — the rule was broken a second time between the review and the ADR (see "Found since this review"). It records both regressions, the rejected second-connection alternative with the measurement that killed it, and the resumability consequence. `c4.md` links to it and gains a table of what is shared between projects and how they are kept apart.

## Testing

* [x] **[High] The real-provider tests are marked, excluded by default, and run nowhere.** — *Fixed.*
  `pytest.ini_options` deselects `-m real_provider`, `make test-real` exists, and no workflow or script ever calls it. Three tests carry the marker, so the only automated check that a real model produces anything at all is `scripts/benchmark_real_dub.py`, which is also run by hand. Every gate in the repository passes against fakes.
  *Done:* `.github/workflows/providers.yml` runs weekly and on demand. It installs FFmpeg, a Deno runtime for yt-dlp's JavaScript challenge, and every provider extra; reports the environment with `germandubi doctor`; runs `make test-real`; and dubs a 60-second excerpt of a real source end to end, uploading the measurement. It gates nothing, on purpose: what it catches is upstream breakage, which arrives on its own schedule and which a contributor cannot have caused.

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

* [x] **[High] Nothing scans dependencies for known vulnerabilities.** — *Fixed.*
  Neither workflow runs `pip-audit`, `osv-scanner`, or npm's audit, and the project pulls a large transitive surface — torch, spacy, stanza, onnxruntime and their dependencies. A GPL-licensed local tool still ships code that parses untrusted media.
  *Done:* `.github/workflows/audit.yml`, on every push and pull request and daily at 05:23 — a disclosure does not wait for the next commit. `pip-audit` runs against the *exported lockfile* rather than the installed environment, because this project's own package is installed editable and is not on PyPI, which `pip-audit` reports as an error that neither `--strict` nor `--skip-editable` can get past. The default install is audited strictly and blocks: it is clean today, and it is what every user gets. The provider extras are audited too but reported rather than enforced — torch is held at 2.2.2 by a `numpy<2` constraint from the separation stack, so those findings cannot be closed by bumping a pin here, and a permanently red gate teaches people to ignore it. Both `pnpm audit --audit-level=high` runs are blocking and clean.

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

* [x] **[Medium] Translation is half finished, and nothing detects the half that is missing.** — *Fixed.*
  `SegmentEditor` and `ErrorAlert` contain no `useT` at all, and `ProjectPage` still has hardcoded English — "Loading project…", "German preview", "The export includes German and original audio tracks." A reader who selects Croatian gets a mixture, which is worse than English throughout because it looks broken rather than untranslated.
  *Done:* both components, the eleven `ProjectPage` strings, and more than the finding listed — project states, job statuses, stage names and segment flags were all rendering the raw value the server sends. `ErrorAlert` now translates a heading from the error's stable code and keeps the server's own sentence underneath as the diagnostic; mirroring the backend's whole message catalogue in the browser would drift within a release. The guard is a test rather than a convention: it parses every component with the TypeScript compiler and fails on JSX text and on translated attributes written as literals, naming file, line and text. Stage and status keys are looked up defensively, so an older bundle against a newer server falls back to the server's English label instead of rendering `stage.deflicker`.

* [ ] **[Low] Voice previews cannot be stopped once started.**
  `VoicePicker` creates an `Audio` element, disables the button while it plays, and offers no way to stop it. A voice sample is short, so this is a small annoyance rather than a fault — but selecting a different voice while one is playing leaves the previous sample playing over the new selection.
  *Do:* turn the button into play/stop, pause the current audio on unmount and on voice change, and keep the element in a ref rather than creating a new one per press.

* [x] **[Low] Queue position is invisible while a second project waits.** — *Fixed.*
  Source inspection is prioritised so a newly added URL is analysed quickly, but once a dub is running the second project's own dub waits behind roughly fifteen stages with nothing on screen explaining the wait. The interface shows a project that is "ready" and apparently idle.
  *Done:* `RunProgress` carries `queue_position` and `queue_length`, and the processing screen says "Waiting for another project to finish" with the position when more than one is queued. The position comes from the same `_runnable_in_claim_order` the worker claims through, shared deliberately: a position derived from a second, similar query would be a position in a queue nobody works from, and the page would confidently show the wrong wait.

---

## Found since this review

Two defects the review did not catch, found by a user adding a second video during a
40-minute dub and getting `500` three times. Both are fixed; both are recorded here because
the review said the concurrency work was done, and it was not.

* [x] **[High] Reporting progress took the write lock and held it for the work that followed.**
  The review's third High finding moved the *stage* out of the job's transaction, which was
  correct and insufficient. `_report` still ended in `session.flush()`, and a handler that
  announces what it is about to do and then does it — `progress(0.1, "using faster-whisper")`
  followed by two minutes of recognition — took the lock with the announcement. Every API
  write in that window failed with "database is locked". The same flush also kept the update
  inside the worker's transaction where the API could not read it, so the progress bar stood
  still between checkpoints.
  *Done:* `_report` commits and renews the lease. Two tests fail against the previous code:
  one creates a project while a stage that reported progress and has no checkpoint is
  running, one reads the progress from another connection before the stage ends.
  *Lesson:* the rule was known and written down, and was broken anyway by the smallest line
  in the handler. It needed a test at the level the defect appears at, not a docstring.

* [x] **[Medium] A create that failed left its project workspace on disk.**
  The workspace directory is made inside the database transaction. The filesystem does not
  roll back, so each failed click left an orphan directory with no row referring to it —
  invisible in the interface, not removed by "delete everything", accounted for by nothing.
  Three accumulated in one session.
  *Done:* the create removes the directory if the transaction does not complete, through the
  artifact store rather than a second transaction, because the failure being recovered from
  is often the database itself. This is the same class as the open `delete_all` finding
  above, which remains.

## Suggested order

The first three High findings are the ones that can produce wrong state rather than
inconvenience: schema ownership, the resumability contract, and the lease. The dependency
scan is High for a different reason — it is the only finding here that someone outside this
repository could exploit, and it is an afternoon's work.

All five High findings are now closed, along with the concurrency ADR, the translation gap
and the invisible queue. What remains is nine Medium and three Low findings, none urgent
enough to hold a release: the application works, the gate is honest, and every finding above
is a known gap rather than a surprise.
