# ADR-0002: Run processing in a separate worker

- Status: Accepted
- Date: 2026-08-30

## Context

Acquisition, media processing, and model inference can run for minutes and can be cancelled
or crash. Running them inside an HTTP request would tie their lifetime to a client
connection and make the browser unresponsive.

## Decision

The API persists a dependency-ordered run and returns immediately. A separate worker claims
jobs under a lease, commits each result atomically, retries bounded transient failures, and
checks persisted cancellation between long operations. API and worker coordinate through
SQLite and persisted artifacts, not an in-memory queue.

## Consequences

The workstation runs two Python processes. In return, work is resumable after either
process restarts, failures remain inspectable, and HTTP latency is independent of model
latency. SQLite lease contention must be measured before supporting multiple workers.
