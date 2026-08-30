# ADR-0009: Use a thin React and TypeScript frontend

- Status: Accepted
- Date: 2026-08-30

## Context

The browser needs routing, long-lived server state, accessible segment editing, and media
preview, but business rules must not be duplicated outside the backend.

## Decision

Use React, strict TypeScript, Vite, and TanStack Query. Generate wire types from FastAPI's
OpenAPI schema and fail the quality gate when they drift. Keep visual drafts local to their
component; the backend decides state transitions and invalidation boundaries.

## Consequences

The frontend remains replaceable and cannot silently invent pipeline behavior. A Node
toolchain is required for development, and user-visible workflows require component and
Playwright coverage.
