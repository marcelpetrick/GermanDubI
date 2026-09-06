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

* [x] **[Medium] `delete_all` deletes every workspace inside a single transaction.** -- *Fixed.*
  `projects.py` pages through projects and calls `uow.store.delete_workspace` for each, all within one unit of work. Filesystem deletion is not transactional: if the transaction rolls back after several directories are gone, the database still lists projects whose files no longer exist.
  *Done:* the rows are committed first and the directories removed afterwards, outside any
  transaction, for both `delete` and `delete_all`. That changes which way the two can
  disagree: an interruption now leaves an unreferenced directory, which costs disk and can
  be cleared by deleting again, rather than rows pointing at files that are gone. A failed
  `rmtree` no longer undoes the deletion either. The write-lock half of the original
  suspicion turned out not to hold for a single delete -- the ORM had not flushed the
  DELETE, so no lock was held -- and did hold for `delete_all` past its second batch.

* [x] **[Medium] Stage retries have no backoff.** -- *Fixed.*
  `_finish_failed` re-queues immediately, so a deterministic failure burns all three attempts in milliseconds and a transient one — a rate-limited download, a busy GPU — retries at the least useful possible moment. The yt-dlp investigation in this repository is a live example: three immediate attempts all failed while the same command succeeded a minute later.
  *Done:* exactly that. Jobs carry `next_attempt_at`, claiming skips those whose time has
  not come, and the waits are five seconds then a minute -- configurable, because the
  deterministic browser run wants zero and an operator may want otherwise. The queue
  position deliberately still counts a job waiting out its backoff: it is a project waiting
  its turn, and dropping it would blank the queue for those seconds.

## Architecture

* [x] **[Medium] `repositories.py` is 1,135 lines holding four repositories and their mappers.** -- *Fixed.*
  Every persistence concern in the application lives in one file: project, segment, artifact and job repositories, plus roughly a dozen row/domain mapping functions between them. Nothing is wrong with the code, but a file this size is where merge conflicts concentrate and where a reader stops being able to hold the whole thing in their head.
  *Done:* as described, plus `events.py`. No mapper was used outside its own section, which
  is what made this a move rather than a redesign: no behaviour, signature or test changed.
  Jobs is still the largest at 440 lines and is the one worth watching -- it holds the claim
  operation, the lease handling and the queue ordering.

* [x] **[Medium] Provider settings are cross-wired through `transcription_provider`.** -- *Fixed.*
  `ProviderRegistry.probe()` and `prosody()` both check `settings.transcription_provider == "fake"`, so selecting a fake transcript provider silently changes two unrelated ports. It works, and the deterministic E2E depends on it, but the coupling is invisible from the setting's name and will surprise whoever changes it next.
  *Done:* the first. Each port has its own setting, and `scripts/e2e-server` names all six
  rather than relying on one to imply another. A test pins both directions so the coupling
  cannot return.

* [x] **[Medium] No ADR records the concurrency and transaction model.** — *Fixed.*
  The rule that a stage runs outside any open write transaction is now load-bearing — it is the difference between a working application and `database is locked` — and it lives only in a commit message and a section of `c4.md`. ADRs exist for smaller decisions (a separate worker, SSE over WebSocket).
  *Done:* written, and it earned its place — the rule was broken a second time between the review and the ADR (see "Found since this review"). It records both regressions, the rejected second-connection alternative with the measurement that killed it, and the resumability consequence. `c4.md` links to it and gains a table of what is shared between projects and how they are kept apart.

## Testing

* [x] **[High] The real-provider tests are marked, excluded by default, and run nowhere.** — *Fixed.*
  `pytest.ini_options` deselects `-m real_provider`, `make test-real` exists, and no workflow or script ever calls it. Three tests carry the marker, so the only automated check that a real model produces anything at all is `scripts/benchmark_real_dub.py`, which is also run by hand. Every gate in the repository passes against fakes.
  *Done:* `.github/workflows/providers.yml` runs weekly and on demand. It installs FFmpeg, a Deno runtime for yt-dlp's JavaScript challenge, and every provider extra; reports the environment with `germandubi doctor`; runs `make test-real`; and dubs a 60-second excerpt of a real source end to end, uploading the measurement. It gates nothing, on purpose: what it catches is upstream breakage, which arrives on its own schedule and which a contributor cannot have caused.

* [x] **[Medium] The frontend has no coverage measurement and roughly a third of its components have tests.** -- *Fixed.*
  Five test files cover fourteen components. The backend enforces 95.1% and the frontend enforces nothing, so the untested half is invisible rather than merely untested. `HelpPage`, `AboutPage`, `VoicePicker`, `PipelineProgress` and `SegmentWorkspace` have no direct tests.
  *Done:* the measurement and the floor, set at what the suite covers today -- 67.85% of
  statements, 69.61% of lines -- and enforced by the gate rather than by a command someone
  remembers to run. The prioritisation stands as written: `VoicePicker` at 33% and
  `useProjectEvents` at 26% are where raising the floor should start.

* [x] **[Medium] There is no error boundary; a render error blanks the page.** -- *Fixed.*
  `grep -rn Boundary frontend/src` returns nothing. Any exception thrown during render unmounts the whole tree, leaving a white page with the explanation only in the console — where a non-developer will never look.
  *Done:* a class boundary above every provider, so a failure in the query client, the
  theme or the locale provider still reaches a page. It reads the catalogue directly rather
  than through `useLocale` for that reason -- a boundary that needed a context could not
  report a failure in the context it needs. It says the work is untouched before it says
  anything else, which is the reader's first question.

* [x] **[Medium] The browser tests cover the happy path only.** -- *Fixed.*
  Both specs drive a successful dub. Nothing exercises a failed stage, a degraded environment, an unavailable source, or a project stopped mid-run — and those are the paths where the interface has the most to say and the most to get wrong.
  *Done:* a failed stage and a run stopped mid-flight. The fake downloader fails for a
  marked source, which is how a deterministic run reaches the path without the server
  needing a mode of its own. The specs assert that the project reaches a failed state, that
  the reason reaches the reader in both places it is shown, and that there is a way on.

* [ ] **[Low] No automated accessibility check, despite deliberate accessibility work.**
  There are 34 `aria-`/`role` attributes, a skip link, a `forced-colors` fallback and focus-visible styling — the intent is clearly there, and nothing verifies it. Contrast in particular is a real risk given a neon palette that was tuned by eye.
  *Do:* add `@axe-core/playwright` and assert no violations on the home, project, help and about pages, in both themes. It is roughly ten lines and it protects work already done.

## Operations and supply chain

* [x] **[High] Nothing scans dependencies for known vulnerabilities.** — *Fixed.*
  Neither workflow runs `pip-audit`, `osv-scanner`, or npm's audit, and the project pulls a large transitive surface — torch, spacy, stanza, onnxruntime and their dependencies. A GPL-licensed local tool still ships code that parses untrusted media.
  *Done:* `.github/workflows/audit.yml`, on every push and pull request and daily at 05:23 — a disclosure does not wait for the next commit. `pip-audit` runs against the *exported lockfile* rather than the installed environment, because this project's own package is installed editable and is not on PyPI, which `pip-audit` reports as an error that neither `--strict` nor `--skip-editable` can get past. The default install is audited strictly and blocks: it is clean today, and it is what every user gets. The provider extras are audited too but reported rather than enforced — torch is held at 2.2.2 by a `numpy<2` constraint from the separation stack, so those findings cannot be closed by bumping a pin here, and a permanently red gate teaches people to ignore it. Both `pnpm audit --audit-level=high` runs are blocking and clean.

* [x] **[Medium] Released artifacts carry no provenance or signature.** -- *Fixed.*
  `release.yml` builds a wheel and an sdist and uploads them. Anyone downloading has no way to verify they came from this repository and this commit, which matters more for a GPL tool people are invited to self-host.
  *Done:* after the install check rather than before it, so nothing is vouched for until it
  has been shown to work. Verifiable with `gh attestation verify <wheel> --repo
  marcelpetrick/GermanDubI`.

* [x] **[Medium] The gate silently removes the providers needed to use the product.** — *Fixed.*
  `uv sync --locked` in `localPipeline.sh` uninstalls the optional extras every run, so the sequence "run the gate, then dub something" leaves a machine that cannot dub. It is documented in three places, which is itself the evidence that it surprises people — it caught this project's own maintainer twice during development.
  *Done:* the first of the two. The gate lists the installed provider distributions before `uv sync`, and restores exactly those extras on the way out — on every exit path, including a failed run and Ctrl-C, which is when nobody is looking. It still runs against the lean set, because a machine with the real stacks must not pass a gate a clean checkout would fail. Alongside it, `scripts/preflight` became the one implementation of the prerequisite check, shared by `make setup` and the gate, and the README stopped listing `yt-dlp` and "a JavaScript runtime" as manual prerequisites — both are already provided, and listing them as manual is how one of them came to be missing. Verified by cloning into an empty directory and running `make setup`, which ends at "Ready to dub".

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

* [x] **[High] Deleting a project while its stage ran killed the worker process.**
  Separation of a 40-minute source was running; the project was deleted; the stage finished
  and tried to write its artifact row for a project that no longer existed. SQLite refused
  with a foreign-key violation, which left the session unusable, and recording "this job
  failed" went through that same session and raised `PendingRollbackError`. Nothing caught
  it, so the worker process ended. Every other project then sat in "probing" indefinitely,
  which reads as a broken probe stage and was an absent worker.
  *Done:* a run that no longer exists counts as cancelled, so a delete stops the work
  promptly and terminates the subprocess rather than letting it finish and write 400 MB into
  a directory that was just removed. A stage's outcome is recorded on a transaction of its
  own, so a poisoned session cannot take down the recording of the failure it caused. And
  the worker loop carries on after an unexpected error instead of exiting, because one bad
  job must never stop processing everything silently.
  *Lesson:* the same one, again. Removing the write-lock defect is what made this reachable
  — the delete would previously have failed with "database is locked". A fix that removes
  one failure mode exposes the next.

## Suggested order

The first three High findings are the ones that can produce wrong state rather than
inconvenience: schema ownership, the resumability contract, and the lease. The dependency
scan is High for a different reason — it is the only finding here that someone outside this
repository could exploit, and it is an afternoon's work.

Every High and every Medium finding is now closed. What remains is three Low ones -- no
automated accessibility check, a wheel smoke test that only asks for a version, and voice
previews that keep playing when the page is left. None of them can produce a wrong result;
all three are worth doing and nothing breaks meanwhile.

The three defects under "found since this review" are the more interesting result. All three
were in code this review had just declared sound, and each was exposed by the fix before it.
That is an argument for the tests that accompany them rather than for more review.
