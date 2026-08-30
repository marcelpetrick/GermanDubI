# ADR-0010: Select only local providers by default

- Status: Accepted
- Date: 2026-08-30

## Context

Transcripts, reference speech, and generated audio can be sensitive. A local workstation
must not send them to a third party merely because a network provider is available.

## Decision

Every provider declares `LOCAL` or `NETWORK`. Automatic selection considers local
providers only. A network provider requires explicit configuration with
`allow_network_providers`; the UI and provider report expose its kind and notes.

## Consequences

The default pipeline can be slower or lower quality than a hosted model but remains
private and predictable. Adding a network adapter also requires clear documentation of
which project data it transmits.
