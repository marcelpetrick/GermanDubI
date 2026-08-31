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
  Separation moved from a hardcoded CPU to the GPU: 244 s for 2400 s of audio, about 10x
  realtime, against roughly 1x on the CPU.
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
| separate | not run | 205.5 s | new work, on the GPU |
| transcribe | 80.7 s | 152.3 s | slower, unexplained |
| total | 509 s | 783 s | with separation included |

Read honestly: assembly improved by the predicted amount on real data. The total grew
because separation now runs at all, which is new work worth 205 s and was previously
absent -- on the GPU rather than the roughly 2400 s it would cost on the CPU. Transcription
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

