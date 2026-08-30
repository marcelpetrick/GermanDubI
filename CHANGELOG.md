# Changelog

All notable changes to GermanDubI are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

During `0.x` the project file format and the HTTP API are still evolving; breaking changes
may occur in MINOR releases and are always listed here.

## [Unreleased]

### Added

- Browser workstation flow for creating and analyzing a project, following pipeline
  progress, previewing and downloading the export, and reviewing, correcting, regenerating,
  and approving individual German segments.
- OpenAPI-generated frontend types with a staleness check in the default quality gate.

### Fixed

- Optional translation and speech providers that are installed but cannot be imported now
  degrade to an available fallback instead of aborting application startup or test
  collection.
