# ADR-0012: Hold the database only in short transactions around a stage

- Status: Accepted
- Date: 2026-09-01

## Context

A stage runs for minutes: transcribing a 40-minute source takes about two, separating it
takes longer. The store is SQLite, which allows one writer at a time, and the API process
writes to the same file whenever a user creates a project, edits a segment or stops a run.

The obvious implementation -- one transaction per job, opened when the job is claimed and
committed when the stage finishes -- makes the worker hold the write lock for the whole
stage. Every write from the API in that window waits out `busy_timeout` and then fails with
`database is locked`, which the browser shows as a bare 500.

This is not hypothetical. It shipped twice.

1. Recording "stage started" happened inside the stage's transaction, taking the lock
   before a model had even loaded.
2. After the stage was moved out of that transaction, reporting progress still ended in
   `session.flush()`. A handler that announces what it is about to do and then does it --
   `progress(0.1, "using faster-whisper")` followed by two minutes of recognition -- took
   the lock with the announcement and held it for the work.

The second is worth dwelling on. The first fix was correct and insufficient, because the
lock was taken by the smallest, most innocuous-looking line in the handler.

Rejected: giving progress reporting its own connection. It was tried. A second *writer*
deadlocks the process against itself while the first connection holds the lock; the test
suite went from 113 seconds to over 600 before it was killed.

## Decision

The database is held only in short transactions, and never across work.

- Claiming a job, announcing a stage, and recording its outcome are each their own
  transaction.
- The stage body runs with no write transaction open.
- `checkpoint()` and `progress()` both **commit**, and renew the job's lease while they are
  there. A stage that writes as it goes therefore lets go repeatedly rather than
  accumulating a lock.
- Cancellation is read on a **separate connection**. A reader never blocks a writer under
  WAL, which is what makes a second connection safe for reading where it is fatal for
  writing. It also has to be separate: the stage's own transaction holds a snapshot from
  before the cancellation was written and would answer "no" forever.

## Consequences

**Handlers must be resumable.** Committing part-way means a stage that fails later leaves
what it had already written, and the retry meets that partial work. The pattern is to look
for your own output before producing it -- speech synthesis skips a segment that already
has audio. A handler that assumed its writes would roll back would corrupt a project on its
second attempt. This is stated in `StageContext.checkpoint`'s docstring, in `AGENTS.md`
section 7, and enforced by two tests: one asserts work committed before a failure survives,
and one runs a handler that fails half-way and asserts the retry reaches exactly the
uninterrupted result.

**Progress becomes visible.** An uncommitted progress report cannot be read by the API's
connection, so before this the processing screen only advanced at checkpoints even though
the stage had been reporting all along.

**A stage can outlive its lease.** Committing at a checkpoint is also where the lease is
renewed, so a legitimately long stage is not mistaken for an abandoned one. A stage with no
checkpoint inside it -- one long external call -- cannot renew, which is why one worker per
data directory is enforced separately with an exclusive `flock` rather than left to the
lease.

**The rule has to be tested, not remembered.** Both regressions were introduced by someone
who knew the rule. `backend/tests/integration/test_worker_concurrency.py` drives the
failure through the real interfaces: it starts a stage that reports progress and never
checkpoints, then creates a project and asserts it does not wait.
