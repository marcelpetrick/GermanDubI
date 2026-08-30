# ADR-0010: Select only local providers by default

- Status: Accepted
- Date: 2026-08-30

## Context

Transcripts, reference speech, and generated audio can be sensitive. A local workstation
must not send them to a third party merely because a network provider is available.

## Decision

Every provider declares `LOCAL` or `NETWORK`. The rule governs the providers that *process*
project content -- transcription, translation, speech synthesis, separation: automatic
selection considers local implementations only, and a network one requires explicit
configuration with `allow_network_providers`. The UI and the provider report expose each
provider's kind and notes.

Source acquisition is deliberately outside that rule. Probing and downloading a remote
source is the user's own explicit request to contact that site, and gating it behind the
same flag would make pasting a URL -- the product's entire entry point -- fail by default.
`yt-dlp` therefore declares `NETWORK` and is still selected automatically for a remote
source, while a local file is probed by a `LOCAL` provider that reads the file's own
metadata and contacts nothing.

The distinction is not "does this touch the network" but "does project content leave the
machine to be processed somewhere else". Acquisition sends a URL the user typed; a network
model provider would send the narration itself.

## Consequences

The default pipeline can be slower or lower quality than a hosted model but remains
private and predictable. Adding a network adapter also requires clear documentation of
which project data it transmits.

The carve-out has to stay narrow and visible, or it becomes the hole the rule leaks
through. Acquisition is the only exempt port, `germandubi doctor` shows every provider's
kind, and any future network adapter for a processing port is subject to the flag.
