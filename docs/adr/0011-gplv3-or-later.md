# ADR-0011: License GermanDubI under GPLv3 or later

- Status: Accepted
- Date: 2026-08-30

## Context

GermanDubI combines a local workstation, a processing pipeline, and provider adapters. Its
license must apply consistently to all project-owned source code and distributions while
remaining distinct from the licenses of optional third-party tools, models, and media.

## Decision

License all GermanDubI-owned code and documentation under the GNU General Public License,
version 3 or any later version, using the SPDX expression `GPL-3.0-or-later`. Copyright is
held by Marcel Petrick (`mail@marcelpetrick.it`). Contributions are welcome and are
accepted under the same project license.

Third-party programs, Python and JavaScript dependencies, provider models, and user media
retain their own licenses. GermanDubI does not relicense or imply redistribution rights for
those assets.

## Consequences

Redistributions and derivative works of GermanDubI must preserve the GPL terms and provide
corresponding source as required by the license. Package metadata, API metadata, release
artifacts, documentation, and the repository license must all identify
`GPL-3.0-or-later`. Provider license information remains a separate runtime concern.
