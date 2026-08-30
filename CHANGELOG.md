# Changelog

All notable changes to GermanDubI are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

During `0.x` the project file format and the HTTP API are still evolving; breaking changes
may occur in MINOR releases and are always listed here.

## [Unreleased]

### Added

- GPL-3.0-or-later project licensing, contribution guidance, and consistent package and
  API license metadata.
- Repository-wide test coverage above 95%, enforced as a 95.1% line-coverage gate.
- Browser workstation flow for creating and analyzing a project, following pipeline
  progress, previewing and downloading the export, and reviewing, correcting, regenerating,
  and approving individual German segments. Approving every segment completes the project.
- OpenAPI-generated frontend types with a staleness check in the default quality gate.

### Fixed

- Probing a long source with many formats and caption languages no longer fails with
  "the source site returned metadata this version cannot read". Captured process output
  was silently truncated at 256 KB, which cut the downloader's JSON metadata in half; a
  caller that parses output now asks for it whole, and any truncation is reported rather
  than blamed on the source.
- Long unpunctuated transcript passages now split at word boundaries instead of producing
  an oversized dubbing segment, and yt-dlp webpage failures are no longer misclassified as
  age restrictions.
- Optional translation and speech providers that are installed but cannot be imported now
  degrade to an available fallback instead of aborting application startup or test
  collection.
- Source checkouts now calculate their version from the current Git state even when a
  previous build left a stale generated version module behind.
