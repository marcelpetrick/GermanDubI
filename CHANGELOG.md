# Changelog

All notable changes to GermanDubI are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

During `0.x` the project file format and the HTTP API are still evolving; breaking changes
may occur in MINOR releases and are always listed here.

## [Unreleased]

### Changed

- `make install-providers` now installs voice/background separation as well, and a new
  `make setup` takes a clean checkout to a machine that can really dub in one command.
  Separation was the one provider no documented step ever installed, so following the
  instructions produced a dub with the English voice still faintly audible under the German.

## [0.2.0] - 2026-08-31

The interface grows up, and four defects that only a real, full-length source could expose
are fixed. A dub of the reference 40-minute video now takes 509 s on CPU, a 0.21x realtime
factor, and reads correctly end to end.

### Added

- Light, dark and follow-the-system themes, chosen by the reader and remembered, on a neon
  palette. The theme is resolved before first paint, so there is no flash on load.
- The interface is available in English, German, Croatian and Mandarin. This translates the
  interface only; dubs remain English to German.
- A Help page explaining the workflow in five steps, listing all sixteen pipeline stages,
  and answering how long a dub takes, what can be edited, and what leaves the machine.
- An About page naming the author, the licence, the repository, the third-party tools and
  their licences, and the providers actually installed, read live from the API.
- The running version is shown in the header on every screen and links to the build detail.
- The segment table can be filtered to flagged, needs-review or failed segments, and
  reports how many of the total are shown.

### Changed

- A run without a real translation provider, German voice or transcript source now fails
  with the command that installs it, instead of silently substituting the placeholder
  providers used by the test suite. Those placeholders do not translate and do not speak, so
  a run that used them completed every stage, reported success, and produced no German.
  Separation keeps its fallback: without it the mix ducks the original audio rather than
  removing it, which is a worse dub but still a dub.
- `germandubi doctor` reports "Ready to dub" only when a real translator and a real German
  voice are present. FFmpeg alone was previously treated as sufficient.

### Fixed

- Scrolling captions no longer reach the dub two or three times over. YouTube restates each
  finished line in the following cue, and because those cues abut rather than overlap the
  repetition was treated as new speech, so segments read "For many years, archaeologists
  puzzled For many years, archaeologists puzzled over how...".
- Mixing a full-length video no longer fails. Ducking named every speech run in a single
  FFmpeg expression, which reached tens of kilobytes on a 40-minute source and was rejected
  with "Cannot allocate memory"; the ranges are now spread over several chained filters.
- Word timing estimated for a caption transcript stays inside its cue instead of running
  past the end and corrupting the order of the cue that follows.
- The word-order invariant accepts the slight overlaps speech recognizers ordinarily emit,
  which previously failed segmentation for any long source.
- Automatic captions are no longer mistaken for manual ones, which made the pipeline prefer
  unpunctuated text over installed speech recognition.
- Dubbing a local file no longer fails at the first stage: source inspection always chose
  the downloader, which cannot inspect a file already on disk.
- `make install-providers` installs speech recognition as well as translation and speech,
  which is what the error messages already told users it would do.
- The browser workflow no longer attaches to a developer's running `make dev` server. It
  takes its own ports and never reuses a server it did not start, so it tests the
  deterministic fixture rather than whatever happens to be listening.

## [0.1.0] - 2026-08-31

First public release. GermanDubI turns an English video into an editable, synchronized
German dub on your own machine.

The complete 40-minute reference source dubs end to end in 492 s on CPU -- a 0.21x
realtime factor -- producing an MKV with a German audio track, the original English kept
alongside it, and German and English subtitles.

### Added

- GPL-3.0-or-later project licensing, contribution guidance, and consistent package and
  API license metadata.
- Repository-wide test coverage above 95%, enforced as a 95.1% line-coverage gate.
- Browser workstation flow for creating and analyzing a project, following pipeline
  progress, previewing and downloading the export, and reviewing, correcting, regenerating,
  and approving individual German segments. Approving every segment completes the project.
- OpenAPI-generated frontend types with a staleness check in the default quality gate.
- `localPipeline.sh`, one quality gate run identically by developers and by CI, covering
  prerequisites, locked setup, every check, both builds, the browser workflow, and a
  production server smoke test.
- Release automation triggered by an annotated `vX.Y.Z` tag. It reruns the whole gate at
  the tagged commit, refuses to publish when the tag, the built version and the changelog
  disagree, verifies the wheel installs and runs, and publishes both artifacts.
- Local media files can be dubbed: they are inspected by a local `ffprobe`-backed provider
  that contacts nothing.
- `scripts/benchmark_real_dub.py`, which takes a real source through the whole pipeline
  with real providers and records a per-stage timing breakdown. Measurements live in
  `docs/benchmarks/`.
- Operations documentation for creating a release and for troubleshooting common failures.

### Changed

- The only word-alignment implementation is no longer named `FakeAlignmentProvider`. It
  runs on every caption-sourced project and is now `ProportionalAlignmentProvider`,
  reported honestly by `germandubi doctor` as an estimate rather than a measurement.

### Fixed

- Probing a long source with many formats and caption languages no longer fails with
  "the source site returned metadata this version cannot read". Captured process output
  was silently truncated at 256 KB, which cut the downloader's JSON metadata in half; a
  caller that parses output now asks for it whole, and any truncation is reported rather
  than blamed on the source.
- Mixing a full-length video no longer fails. Ducking named every speech run in a single
  FFmpeg expression, which reached tens of kilobytes on a 40-minute source and was rejected
  with "Cannot allocate memory"; the ranges are now spread over several chained filters.
- Dubbing a local file no longer fails at the first stage. Source inspection always chose
  the downloader, which cannot inspect a file that is already on disk.
- Long real sources no longer fail during segmentation. Two separate causes: word timing
  estimated for a caption transcript could run past the end of its cue and collide with the
  next one, and the word-order invariant rejected the slight overlaps that speech
  recognizers ordinarily emit.
- Automatic captions are no longer mistaken for manual ones. A source with no manual
  captions has its automatic track written under the same file name a manual track would
  use, so the pipeline preferred unpunctuated text over installed speech recognition and
  quietly produced worse German.
- An optional provider package that is only half present now degrades to the fallback
  instead of raising past the handler meant to catch it.
- `germandubi doctor` reports every selectable provider, including source inspection for
  local files and word alignment, which it previously omitted.
- Long unpunctuated transcript passages now split at word boundaries instead of producing
  an oversized dubbing segment, and yt-dlp webpage failures are no longer misclassified as
  age restrictions.
- Optional translation and speech providers that are installed but cannot be imported now
  degrade to an available fallback instead of aborting application startup or test
  collection.
- Source checkouts now calculate their version from the current Git state even when a
  previous build left a stale generated version module behind.
