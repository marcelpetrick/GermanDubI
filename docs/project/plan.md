# GermanDubI completion plan

This document is the committed execution ledger for bringing the first public release to
a safe, reproducible state. Every completed step is marked in the same atomic commit as
the work it records. The repository is prepared locally; publishing and pushing remain
the maintainer's responsibility.

Status values: `PENDING` · `IN PROGRESS` · `COMPLETE`.

## 1. Audit the inherited implementation · `COMPLETE`

- Compared the implementation with `docs/product/vision.md`, `AGENTS.md`, the C4 documentation, and
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

## 13. Finalize the local v0.1.0 release state · `COMPLETE`

- Moved the release notes out of `Unreleased` into a dated `## [0.1.0]` section, and
  verified the release workflow's own guards against the real file: the version check
  matches and the note extraction returns the section and stops at the right boundary.
- Created an annotated local `v0.1.0` tag on the fully green commit, and confirmed the
  version derived from it is exactly `0.1.0` with no development or dirty suffix.
- Not pushed. Pushing the commits and the tag is the maintainer's decision; the tag
  workflow will then rerun the whole gate and create the public GitHub release.

## 14. Give the workstation a neon identity with real light and dark modes · `COMPLETE`

- Retune the existing token set to a neon palette -- pink and cyan, gradient accents, glow
  rather than flat fills. The tokens already exist; the rules stay, the values change.
- Support three theme states: light, dark, and follow-the-system. The current stylesheet
  only reacts to `prefers-color-scheme`, so a reader cannot override their OS.
- Keep the glow decorative. Neon is used for borders, accents and shadows, never for body
  text, so contrast does not depend on the aesthetic. Honour `prefers-reduced-motion`.
- Acceptance: both themes are legible, the choice persists across reloads, and no text
  falls below its current contrast.

## 15. Let the interface speak the reader's language · `COMPLETE`

- Offer English, German, Croatian and Mandarin for the interface, chosen in the header and
  remembered, defaulting to the browser's language.
- Keep it dependency-free and typed: a locale is a record keyed by the English catalogue,
  so a missing or misspelled key fails `tsc` rather than rendering a blank.
- State plainly that this is the *interface* language. The dub is English to German in
  `0.x` regardless, and conflating the two would be a cruel surprise.
- Acceptance: every visible string comes from the catalogue, all four locales are complete,
  and a test proves completeness rather than trusting review.

## 16. Explain the product and credit what it is built on · `COMPLETE`

- Add a Help page showing what the pipeline actually does: the sixteen stages, what the
  reviewer can change, and what happens when they change it.
- Add an About page naming the tools and models used and their licences, the author, the
  GPL-3.0-or-later terms, and where to find the project on GitHub. It reads live provider
  data rather than a hand-written list that would drift.
- Make the running version visible in the interface, not only in the footer.
- Acceptance: both pages are reachable from every screen and state nothing the repository
  cannot back up.

## 17. Round out the review loop · `COMPLETE`

- Compare against what comparable dubbing tools offer and adopt what is genuinely useful
  at this scope, rather than copying feature lists.
- Filtering the segment table is the clear gap: the review loop is "find what needs
  attention", and 500 rows with no way to narrow them is the difference between usable and
  not. Flagged, unapproved and failed are already in the data.
- Improve the states around the work: what to do when there are no projects, what a
  degraded environment means, and what each pipeline stage is doing while it runs.
- Acceptance met. The segment table filters to flagged, needs-review and failed, and
  reports how many of the total are shown. The editor follows the filter rather than
  stranding itself on a hidden row.
- Also improved the states around the work: an empty project list now says what to do and
  links to Help, and a degraded environment names the command to run instead of listing
  tools.
- Compared against comparable tools, the remaining gaps are a media preview scrubber and
  keyboard navigation of the segment list. Both are worth doing and neither is a blocker
  for a review pass, so they are recorded rather than rushed.

## 18. Use the hardware that is actually present · `COMPLETE`

Measured starting point, from `docs/benchmarks/real-dub-full.json`: 509 s for a 2400 s
source, before separation became a default. Where that time goes, largest first --
assemble 124 s, synthesize 88 s, transcribe 81 s, export 67 s, fit 54 s.

- **Select a compute device, and say which one was used.** There is no device setting at
  all today. Speech recognition passes `auto` and so already finds a GPU; separation is
  hardcoded to `cpu` and never will. On this machine that is the difference between about
  1x realtime and 5.8x for the slowest provider in the pipeline, and separation now runs
  by default. Add a `device` setting, honour it everywhere, and report the resolved device
  in `doctor` so a slow run has a visible cause.
- **Fix assembly, which is the slowest stage and should be the cheapest.** It builds one
  FFmpeg input per segment, so a 500-segment dub means a 500-input filter graph. This is
  the same shape as the ducking expression that could not be evaluated at all: work that
  grows with segment count in a single command.
- **Look for parallelism that is genuinely free.** Speech synthesis is per-segment and
  sequential on a 20-thread machine. Whether Piper can be driven concurrently needs
  measuring rather than assuming.
Done, and what was measured:

- **Device selection.** `GERMANDUBI_DEVICE` (`auto`/`cpu`/`cuda`), resolved once in
  settings so every provider agrees, reported by `doctor` and recorded in the benchmark.
  Recognition already asked for `auto` and already found the GPU, so the change affects
  separation alone, which was hardcoded to the CPU.

  Measured head to head on 120 s of the reference source's own audio: **14.2 s on the GPU
  against 50.5 s on the CPU, a factor of 3.6**. An earlier note in this plan claimed a
  factor of ten, extrapolated from a six-second clip where loading the model dominated the
  run; that figure was wrong and is corrected here. On the full source, separation costs
  205 s on the GPU and would cost roughly 730 s on the CPU -- about nine minutes saved on a
  forty-minute video, which is worth having and is not the order of magnitude first
  claimed.
- **Assembly.** Mixed in batches of fifty rather than one graph over every segment. On 400
  clips laid out like a real dub, 94.4 s became 33.1 s with output differing by -91 dB,
  the sixteen-bit noise floor.
- **Parallel synthesis: not done, and not on evidence of value.** Investigating assembly
  turned up something that matters more, below.

Found while measuring, and deliberately not fixed here:

- **`adelay` into `amix` intermittently deadlocks in FFmpeg n9.0.1.** The process spins at
  100% CPU and never emits a frame, roughly half the time on assembly-shaped graphs. It is
  pre-existing and not caused by the batching: the previous single-pass implementation
  fails at the same rate on the same input, 1 of 3 attempts each. The process timeout and
  stage retry already reduce it to a slow stage rather than a hung run, which is why it had
  gone unnoticed. Fixing it properly means either an FFmpeg upgrade or replacing the mixing
  strategy, and neither belongs in a change made to speed something up.

Full before-and-after on the reference source, both on an idle machine
(`docs/benchmarks/real-dub-full.json`):

| stage | before | after | |
| --- | --- | --- | --- |
| assemble | 124.3 s | 48.9 s | 2.5x faster, as predicted |
| separate | not run | 205.5 s | new work; ~730 s if it ran on the CPU |
| transcribe | 80.7 s | 152.3 s | slower, unexplained |
| total | 509 s | 783 s | with separation included |

Read honestly: assembly improved by the predicted amount on real data. The total grew
because separation now runs at all, which is new work worth 205 s and was previously
absent. The GPU is why that number is 205 s rather than roughly 730 s. Transcription
took nearly twice as long as in the earlier reference for reasons not established here;
both runs used the same GPU and the same model, so it is recorded rather than explained,
and is worth investigating before any further performance claim rests on it.

## 19. Let the reviewer choose the German voice, and hear it first · `COMPLETE`

Eight German voices are already known to the code, and none of them is reachable: the voice
comes from a single global setting that nothing in the product surfaces. Choosing a narrator
is the most consequential creative decision in a dub, and it is currently made for the user.

- **Make the voice a property of the project**, chosen when it is created and shown
  afterwards, rather than a machine-wide setting. Two projects on one machine should be
  able to use different narrators.
- **Publish the catalogue.** An endpoint listing each voice with its quality tier and
  whether its model is already downloaded, so the interface never guesses and never offers
  something that cannot run.
- **Let the user hear each voice before committing.** A short German sample, synthesized
  once on demand and cached. A dropdown of identifiers like `de_DE-pavoque-low` asks
  someone to choose a narrator they have never heard; a play button answers the question
  the list poses.
- **Raise the audio quality of the result.** The export is AAC at 192 kbit/s and the
  default voice is the medium model when a high one exists. Both are defensible defaults
  and neither is the best the pipeline can do.
Done. The voice is a project property with a migration for existing databases, `GET
/voices` publishes the catalogue, `GET /voices/{voice}/sample` returns cached audio, and the
picker with its play button sits beside the URL field.

Quality, measured rather than assumed: the tier in a Piper voice name is a real difference
in fidelity, not a label. `de_DE-thorsten-high` renders at 22.05 kHz and `de_DE-eva_k-x_low`
at 16 kHz, which is why the tier is shown in the dropdown. The default voice moves to
`high` and the export to AAC 256 kbit/s; Piper's 22.05 kHz output remains the ceiling and no
export setting can lift it.

## 20. Stop a second video from breaking the first · `COMPLETE`

Adding a URL while a dub was running returned `500 Internal Server Error`:

    sqlite3.OperationalError: database is locked
    [SQL: INSERT INTO events ...  'project_created' ...]

Two separate defects, and the visible one is not the one that was suspected.

### The crash: a write lock held for the length of a stage

`WorkerProcess._execute` opens one unit of work, writes a `stage_started` event into it
immediately -- which takes SQLite's write lock -- and only then runs the stage handler. The
transaction stays open until the stage finishes. Transcription of a 40-minute source took
123 s, so the write lock was held for 123 s, and `POST /projects` waited out its 10 s
`busy_timeout` and failed.

WAL and `busy_timeout` are already configured and cannot help: they make a *brief* conflict
wait, not a two-minute one. The fault is the duration of the transaction, not the settings.

- Run the stage outside the write transaction. Claiming the job, recording that it started,
  and recording how it ended are three short transactions; the work between them holds no
  lock.
- Progress updates and events are advisory rather than part of a stage's result, so each
  becomes its own short write instead of riding inside the stage's transaction.
- Keep a stage's *results* atomic. That is worth preserving; holding the lock while a model
  runs is not.

### The stall: a cheap probe queued behind an entire dub

`claim_next` is strict FIFO by creation time, so analysing a newly pasted URL waits behind
every remaining stage of the run already in progress. Measured on a reproduction: the new
project's probe sat at **position 15**, behind all fifteen remaining jobs.

Nothing is broken by this -- the queue is fair and the work is correctly serialised -- but
the user pastes a URL and the interface does nothing for many minutes, which is
indistinguishable from a hang.

- Give source inspection priority over pipeline work. It costs a second or two and is what
  the user is waiting on; a dub already running is not harmed by being interrupted at a
  stage boundary.
- Show the queue position, so waiting is legible rather than mysterious.

### Not a problem, and deliberately not changed

Runs do not need isolating from each other. One worker claims one job at a time, each
project has its own workspace, and the claim is atomic. Adding per-run isolation would
solve a problem the system does not have.

Acceptance met. `backend/tests/integration/test_worker_concurrency.py` creates a project
while a stage is running and asserts it returns in under five seconds; against the previous
worker it fails with the exact `OperationalError` after waiting out the busy timeout. A
second test asserts a newly added URL is the next job claimed rather than the sixteenth.

One thing learned the hard way and worth keeping: the first attempt gave progress reporting
and cancellation their own database connections. That deadlocks the process against itself
-- a second connection cannot write while the first holds the lock, and the first will not
commit until the handler returns. The test suite went from 113 s to over 600 s and had to be
killed. Progress and cancellation stay on the stage's connection; what changed is how long
that connection holds the lock.

## 21. Prove two videos in one browser session · `COMPLETE`

Two videos are now safe to queue, and nothing demonstrates it. The browser workflow drives
one project through one dub.

- Extend the deterministic browser test to create two projects with different URLs, dub
  both, and check both results. It runs against the fake providers, so it stays in the
  gate: what is under test is the queue, the interface and the absence of errors, none of
  which needs a real model.
- **Fail the test on browser console errors and on unhandled page errors.** "No warnings
  appeared" is only meaningful if something is watching, and nothing currently is.
- Add an opt-in variant that uses real providers and real URLs for the times a human wants
  end-to-end proof. It cannot live in the gate: it needs the network, the optional model
  stacks and several minutes.
Done, in the gate. `e2e/tests/two-videos.spec.ts` creates two projects from different URLs,
dubs both, and checks each one's export. Console errors and warnings, unhandled page errors
and any HTTP 5xx are collected throughout and asserted empty -- the 5xx watch matters most,
because the original defect produced a 500 that never reached the console.

The opt-in real-provider variant is **not** built. The deterministic run proves the queue,
the interface and the absence of errors, which is what was broken; a real-source browser
test would take a quarter of an hour, need the network and the model stacks, and duplicate
what `scripts/benchmark_real_dub.py` already does end to end. Recorded rather than
silently dropped.

## 22. Let the user stop a run and clear their work · `COMPLETE`

- **Stop.** A cancel endpoint already exists and the interface never calls it. Worse, it
  would not work if it did: `ProcessRunner` is constructed without its `cancelled`
  callback, so cancelling never terminates the ffmpeg, yt-dlp or Demucs process actually
  doing the work. A stage would notice only at its next checkpoint, and a two-hundred
  second separation has none inside it. Wire cancellation through to the process tree, then
  put the button in the interface.
- **Reset.** Deleting one project exists; clearing everything does not. Add it as one
  endpoint rather than a loop of deletes from the browser, so a half-finished clear cannot
  leave orphaned workspaces behind.
- **Say what the buttons do before they are pressed.** Stop abandons work in progress and
  keeps what finished; reset destroys every project and its files. The second is
  irreversible and must ask first.
Done. Cancellation reaches the process tree through the shared process runner, stop is
offered per project in the list as well as on the project page, and clearing everything is
one endpoint that cancels first so a stage cannot recreate the directory it was deleted
from. Every action carries an explanation, in all four languages.

The cancellation test is load-bearing: with the runner wiring removed it waits out the full
sixty-second subprocess instead of stopping within one.

## 23. Make a second video safe, visible, and explicable · `COMPLETE`

Raised by a real session: a 40-minute dub was running, a second URL was pasted, and the
browser answered "something went wrong. Check the server log for details." Three times.

Four separate faults, found by reading the evidence rather than guessing. The recorded
events showed a progress report at 11:15:20 and then nothing until the run was cancelled at
11:17:34, and the data directory held three project workspaces with no matching database
rows -- one per click.

- **The write lock was held for the length of the work.** Moving the stage out of the job's
  transaction had been done already; what had not was progress reporting, which ended in a
  flush. `handle_transcribe` announces "using faster-whisper" and only then recognises
  speech, so the lock was taken by the announcement and held for the two minutes that
  followed. Every API write in that window waited out the 10-second busy timeout and
  failed. Reporting now commits and renews the lease, exactly as a checkpoint does. Two
  tests, both failing against the previous code: one creates a project while a stage that
  reported progress and has no checkpoint is running, one asserts a second connection can
  read the progress before the stage ends -- because the same flush also made the progress
  bar stand still.
- **A failed create left its workspace behind.** The directory is made inside the database
  transaction and the filesystem does not roll back, so each failure left an orphan that
  nothing accounted for and "delete everything" did not remove. The create now undoes it,
  through the artifact store rather than another transaction, because the failure being
  recovered from is often the database itself.
- **The message was a shrug.** Lower case, and it named a log that did not exist: output
  went to the stderr of whichever terminal started the server. There is now a rotating file
  at `<data_dir>/logs/germandubi.log`, every unexpected error carries an eight-character
  reference logged with its traceback, and the error body carries both the reference and
  the path. `germandubi doctor`, the help page and the troubleshooting guide name the same
  path -- the help page reads it from the running server rather than hardcoding a guess.
- **The wait was invisible.** A project queued behind another showed a bar at zero with no
  running stage, which is indistinguishable from a hang. `RunProgress` now carries
  `queue_position` and `queue_length`, computed from the same claim order the worker
  follows -- a second, similar query would be a position in a queue nobody works from.

The isolation model itself was already right and is now written down: one worker under an
exclusive `flock`, one workspace per project, short write transactions, one claim order,
one lease per job. `docs/adr/0012-short-transactions-around-stages.md` records it with the
rejected alternative, and `c4.md` has a table of what is shared and how projects are kept
apart.

Also in this step, because the same session made it obvious: the interface was half
translated. `SegmentEditor` and `ErrorAlert` used no catalogue at all, `ProjectPage` had
eleven hardcoded strings, and every status badge, stage name and segment flag rendered the
raw value the server sends. All four languages are now complete, and a test parses every
component with the TypeScript compiler and fails on JSX text written as a literal, so the
next English string cannot be added silently.

## 24. Bootstrap in one command, and survive a delete mid-dub · `COMPLETE`

Two more faults from the same session, both reported by watching it happen rather than by
reading code.

- **The worker died and took everything with it.** A 40-minute separation was running when
  the project was deleted; the stage finished, wrote its artifact row for a project that no
  longer existed, and SQLite refused with a foreign-key violation. That poisoned the
  session, so recording the failure raised in turn, and the exception left `run_once`, left
  `run_forever`, and ended the process. Every other project then sat in "probing"
  indefinitely — which reads as a broken probe stage and was an absent worker. Reachable
  only *because* step 23 stopped the worker holding the write lock: the delete would
  previously have failed with "database is locked". Three fixes, because one is not enough:
  a run that no longer exists counts as cancelled (so a delete stops the subprocess rather
  than letting it write 400 MB into a deleted directory), a stage's outcome is recorded on a
  fresh transaction, and the loop carries on after an unexpected error.
- **A clean clone did not reliably become a working installation.** `make setup` installed
  without checking that the four host prerequisites were there, so a missing `ffmpeg` or a
  Node from two years ago surfaced much later as something that looked like a bug here. And
  the README listed `yt-dlp` and "a JavaScript runtime" as manual prerequisites when both
  are already provided — which is how one of them came to be missing in the first place.
  `scripts/preflight` is now the single check, run by `make setup` and by the gate.
- **The gate disabled the product it was testing.** `uv sync --locked` uninstalled the
  provider extras every run, so "run the gate, then dub something" left a machine that could
  not dub. It now restores what it found, on every exit path including a failed run and
  Ctrl-C. The gate still runs lean: a machine with the real stacks must not pass a gate a
  clean checkout would fail.

Verified the way the claim is made: cloned the repository into an empty directory, ran
`make setup`, and read the closing `doctor` report — "Ready to dub".

## 25. Put detailed documentation under one discoverable roof · `COMPLETE`

- Kept `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, and `AGENTS.md` at
  the repository root because GitHub, security tooling, and contributors expect them
  there.
- Moved the product vision, project plan, open-question ledger, and historical deep review
  into purpose-named areas under `docs/`.
- Added `docs/README.md` as the documentation map and updated every prose, source-code,
  generated-schema, and contributor reference to the canonical paths.
- Acceptance: all local Markdown links resolve, generated API documentation is current,
  the full `make check` gate passes, 820 backend tests retain 95.22% line coverage, and all
  55 frontend tests pass.

## 26. Stop the assembly stage from hanging · `COMPLETE`

- Reproduced the hang against the real clips of a 40-minute dub: of ten assembly batches,
  one never finished -- 100% CPU, output file frozen at the byte, indefinitely. The other
  nine took between one and eight seconds.
- Narrowed it from fifty clips to **two**, and found it is not deterministic: the same
  command on the same files finished instantly on some runs and hung forever on others.
  `-filter_complex_threads 1` did not change that, so it is not filter threading.
- Isolated the cause to the shape of the tail of the graph. An open-ended `apad` generates
  silence forever and depends on whatever follows it to stop asking; behind an `amix` whose
  inputs end at different times, the `atrim` that followed it intermittently never does.
  Bounding the pad instead (`apad=whole_dur=`) and letting the output option `-t` cut an
  over-long mix removes the failure: 0 hangs in 20 runs of the arrangement that hung 9 times
  in 12, and 8 for 8 on the batch that had never once completed.
- Verified the change is not merely a different graph but the *same* audio: the new graph's
  output is byte-for-byte identical to the old graph's on every batch the old graph managed
  to finish.
- Bounded each assembly pass at the running time of the video itself, floored at five
  minutes and capped by the process runner's own default. A pass that has not finished in
  the time the video lasts is not making progress; previously it burned the global one-hour
  timeout and was then retried twice.
- Gave `concatenate_speech` an `on_batch` callback and had the stage report through it, so a
  long assembly moves the progress bar, renews its lease, and can be cancelled between
  batches instead of going silent for the whole run.
- Acceptance: the full gate passes; a new integration test runs the exact arrangement that
  used to hang ten times over and fails in 30 seconds if it returns; unit tests pin the
  bounded pad, the absence of `atrim`, the timeout bound, and the per-batch reports.

## 27. Outstanding · `OPEN`

Everything below is known, deliberate, and not done. It is written here rather than carried
in someone's head, and each item says what would close it.

### Blocked on this machine, not on the code

Three parts of the container work are written and unverified, each because this development
machine lacks the thing that would exercise them. None is a defect; all three are claims
nobody has checked.

- **`docker compose up`.** No Compose plugin installed here. The file parses and the two
  commands its services run were both exercised directly, so the risk is in the YAML rather
  than in the application. *Closes when:* someone with `docker-compose-plugin` runs it once.
- **The GPU profile.** No NVIDIA Container Toolkit here. *Closes when:* run on a host that
  has it, confirming `germandubi doctor` inside the container reports `GPU (cuda)`.
- **The publish workflow.** GitHub Actions cannot run locally, and the file was rejected
  outright by GitHub for using `secrets` in a step's `if`, which is not one of the contexts
  available there. An unparseable workflow fails in zero seconds and is listed by its path
  instead of its name, which is easy to read as "it simply did not run" -- so it published
  nothing, and `docker pull` answered `denied`. The conditions now go through job-level
  `env`, which may read secrets. *Closes when:* a version tag is pushed, the run goes green,
  and `docker pull` from a clean machine returns a working image.

### One-time account setup, before anyone can pull

- **Make the GHCR package public.** A package is created private, and an anonymous pull of
  a private package is refused with `denied` -- the same word the registry uses for a
  package that does not exist, so the two are indistinguishable from the client. It stays
  private until someone opens the repository's *Packages* section and changes it, and until
  then the `docker pull` line in the README is a promise the registry will refuse.
- **Docker Hub and Quay secrets.** `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` and
  `QUAY_USERNAME` / `QUAY_TOKEN`. Each registry is skipped silently when its pair is absent,
  so publishing works today and reaches only GHCR.
- **The registry listing pages.** A short description and a long one, neither of which a
  registry takes from the image. Both are written and ready to paste in
  `docs/operations/docker.md`.

### Dependency majors, each rejected with a reason

Both were tried, measured, and reverted. Neither is a "someday"; each has a specific
condition that would change the answer.

- **TypeScript 5.9.3 → 7.0.2.** `typescript-eslint` 8.69.0 refuses to load against TS 7 and
  says so, pointing at its own tracking issue for TS ≥ 7.1. Adopting it today means no
  TypeScript linting at all. TS 7 also removed `baseUrl`, which `tsconfig.json` uses.
  *Closes when:* typescript-eslint ships TS 7 support; then the `baseUrl` removal is a
  small, separate change.
- **pnpm 10.34.5 → 11.25.0.** pnpm 11 no longer reads `pnpm.onlyBuiltDependencies` from
  `package.json`, which this repository uses for esbuild, and it wants to purge
  `node_modules`. That is a migration, not a bump: move the setting to
  `pnpm-workspace.yaml`, regenerate both lockfiles, confirm esbuild still builds, and update
  what CI and both `engines` fields expect.

### Still open from the deep review

Eleven findings, eight Medium and three Low, listed in
[`docs/reviews/deep-review.md`](../reviews/deep-review.md) with what each would take. None
is urgent; the ones most likely to be felt are the missing error boundary, which blanks the
page on a render error, and `delete_all` removing workspaces inside a single transaction --
the same class of defect as the create that left orphaned directories.

### Ideas, deliberately not scheduled

[`future_features.md`](../../future_features.md) holds twenty-two, with what each is worth
and what it would cost, and a list of what is deliberately not worth building. The three
cheapest real wins named there: the glossary UI, which is implemented and tested and never
populated; a local LLM translator, which the provider port was designed for; and speaker
diarization.
