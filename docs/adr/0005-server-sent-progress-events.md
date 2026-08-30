# ADR-0005: Use server-sent events for progress

- Status: Accepted
- Date: 2026-08-30

## Context

Pipeline communication is command/response from browser to API but predominantly progress
updates from API to browser. Updates must survive refreshes and temporary disconnects.

## Decision

Commands use REST. Progress uses SSE with persisted, monotonically sequenced events. The
browser reconnects through native `EventSource`; `Last-Event-ID` lets the API replay missed
events. Streams have a bounded lifetime and reconnect automatically.

## Consequences

The protocol stays one-way and simple, with no custom WebSocket lifecycle. Events need a
future retention policy, tracked by Q-D4, and proxies must not buffer the stream.
