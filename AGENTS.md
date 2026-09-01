# AGENTS.md — How to work in this repository

This file is the operating manual for any agent (human or AI) making changes to
GermanDubI. It is deliberately prescriptive. Read it before the first edit.

Companion documents:

| Document | Role |
| --- | --- |
| [`vision.md`](vision.md) | North star. Product vision and target architecture. Rarely changes. |
| [`questions.md`](questions.md) | Every unresolved design/architecture question. Append, never silently drop. |
| [`docs/adr/`](docs/adr/) | Decisions that are expensive to reverse, once resolved. |
| [`CHANGELOG.md`](CHANGELOG.md) | Release-relevant behaviour changes. |

---

## 1. The product in one paragraph

GermanDubI turns an **English** single-narrator video into an **editable, synchronized
German dub**. It is a local-first workstation, not a one-shot script. Every intermediate
artifact is persisted, every stage is resumable, and any segment can be corrected and
regenerated without rerunning the whole video. English→German is the only supported
language pair in `0.x`; do not generalize the pipeline to other pairs before it works
well for this one.

---

## 2. Non-negotiable engineering rules

### 2.1 Layering

```text
api / cli / worker   →   application   →   domain
                              ↑
                    infrastructure (implements application ports)
```

* `domain/` imports **only** the standard library. No FastAPI, no SQLAlchemy, no Pydantic,
  no `yt-dlp`, no FFmpeg, no provider SDKs.
* `application/` defines **ports** (Protocols) and depends on `domain` only.
* `infrastructure/` implements ports. Nothing imports *from* infrastructure except the
  composition root (`api/dependencies.py`, `worker/runner.py`, `cli/main.py`).
* These rules are executable: `backend/tests/unit/test_architecture.py` fails the build
  when they are broken. Do not weaken that test to make a change pass.

### 2.2 The segment is the unit of everything

The core domain object is a **time-bounded speech segment**, not the video and not the
transcript. Review, retry, caching, translation, synthesis, timing correction and QA all
operate per segment. When adding a feature, ask "what does this mean for one segment?"

### 2.3 Non-destructive processing

Never mutate a source artifact or a previous result. Human edits create **revisions**;
the "current" value is a pointer. Regeneration writes a new artifact and repoints.

### 2.4 Time is integer milliseconds

Never store or compare timeline positions as floating-point seconds. Convert at the
boundary (FFmpeg, provider output) and immediately move to `int` milliseconds.

### 2.5 Provider independence

No application or domain code may import a specific model implementation. Everything goes
through a port (`TranscriptionProvider`, `TranslationProvider`, `TTSProvider`, ...).
Every provider implementation must pass the shared contract test suite. Every provider
declares `LOCAL` or `NETWORK` so the UI can tell the user what leaves the machine.

### 2.6 External processes

All external programs run through `infrastructure/processes/runner.py`: argument arrays
only, never a shell, always a timeout, always cancellable, always bounded output capture.
`subprocess` must not be imported anywhere else. This is enforced by an architecture test.

### 2.7 Untrusted input

The source URL and the downloaded media are untrusted. Validate URLs against the
allowlist in `domain/value_objects/source_url.py`. Every path derived from external data
is resolved and checked to stay inside the project workspace before use.

### 2.8 Reproducibility

Every generated artifact records: application version, provider id, model id, input
content hash, configuration hash, and creation time. If you add a generation step, you add
its provenance.

### 2.9 A working version beats a newer one, once you know why

Dependencies are pinned to exact versions and normally kept at the latest stable release.
When a newer release breaks something that works, pin back to the version that works. A
dependency exists to do a job; a release that stops doing it is not an upgrade.

Three things go with the pin, and none is optional:

- **A comment at the pin** naming what broke, with a case that reproduces it. A bare
  downgrade is indistinguishable from neglect six months later, and the next person
  updating dependencies will undo it.
- **Verification that the older version is otherwise sound.** Check the cases the newer one
  handled before assuming the downgrade is free.
- **An intention to move forward.** Holding back is temporary, especially for anything
  tracking a moving target such as a site downloader, where staying behind eventually
  breaks more than it fixes.

The order matters, too: **diagnose before pinning back.** A downgrade that "fixes" the
symptom without explaining it usually means the cause is somewhere else, and the pin then
outlives the problem it was meant to solve while nobody dares remove it.

Worked example, including the mistake. A video failed to download and the obvious suspect
was the newest `yt-dlp`: the previous release handled it. That comparison was wrong,
because the two versions were also two different installations. The same version failed in
one and worked in the other. The actual cause was a missing optional dependency -- YouTube
requires a solved JavaScript challenge, and without `yt-dlp-ejs` and a JS runtime the
downloader reports "This video is not available" for a video that plainly is. Pinning back
would have hidden that and lost six weeks of upstream fixes for nothing.

---

## 3. Versioning — how each commit gets a version

**Never hand-edit a version number. There is no `VERSION` file to bump.**

`setuptools-scm` derives the version from Git:

```text
tag v0.3.0            → 0.3.0
3 commits later       → 0.3.1.dev3+g1a2b3c4
dirty working tree    → 0.3.1.dev3+g1a2b3c4.d20260830
```

* Every commit therefore has a unique, monotonically advancing development version.
* A **release** is an annotated tag `vMAJOR.MINOR.PATCH`, created only when `main` is
  green and `CHANGELOG.md` has been updated.
* SemVer during `0.x`: MINOR may break the HTTP API or project format — say so in the
  changelog. PATCH is compatible fixes only.
* The version is exposed at `GET /api/v1/meta` and by `germandubi version`, and is
  written into every export's metadata.
* The **API version** (`/api/v1`) and the **project format version** are versioned
  independently of the build version. Do not conflate them.

Release checklist:

```bash
make check                 # green
$EDITOR CHANGELOG.md       # move Unreleased → the new version
git commit -m "docs: release notes for v0.3.0"
git tag -a v0.3.0 -m "v0.3.0"
make version               # confirms 0.3.0
```

---

## 4. Commit discipline

**Atomic commits.** One coherent change. The repository must build and pass tests at
every commit, not only at the end of a branch.

Conventional Commits, with a body explaining *why*:

```text
feat(worker): claim jobs with a lease so a crashed worker releases work

Jobs were previously marked RUNNING with no owner, so a worker killed
mid-stage left the job permanently unclaimable. The claim now records a
lease deadline; the planner reclaims expired leases.
```

Allowed types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`,
`revert`. Scopes match the package boundaries: `domain`, `app`, `infra`, `api`, `worker`,
`cli`, `frontend`, `e2e`, `docs`, `ci`.

Rules:

* Do not mix a refactor with a behaviour change.
* Do not mix generated output (lockfiles, OpenAPI client) with hand-written logic unless
  the generation is the point of the commit.
* Never commit media, model weights or anything under `data/`.
* Lockfiles (`uv.lock`, `pnpm-lock.yaml`) and Alembic migrations **are** committed.

---

## 5. Definition of Done

A change is done when, where applicable:

- [ ] implementation and full type annotations (`mypy --strict` clean)
- [ ] docstrings on public application/domain APIs (Google style)
- [ ] unit tests for the logic; property tests for invariants worth stating
- [ ] API/integration test if a route or a worker stage changed
- [ ] E2E test updated if a user-visible workflow changed
- [ ] Alembic migration if persistence changed
- [ ] `docs/` and an ADR updated if a boundary or an expensive decision changed
- [ ] `questions.md` updated if you discovered or resolved an open question
- [ ] `CHANGELOG.md` entry if the behaviour is release-relevant
- [ ] `make check` passes

Happy-path code that runs is not done.

---

## 6. Testing rules

The suite must be fast enough that it actually gets run. Default CI needs **no GPU, no
network, no YouTube, no multi-gigabyte model**.

| Level | Location | Uses |
| --- | --- | --- |
| Unit / property / golden | `backend/tests/unit` | pure functions, invariants, serialization |
| Provider contract | `backend/tests/contract` | every implementation of a port, fakes in CI |
| API | `backend/tests/integration` | FastAPI test client, temp SQLite, temp artifact root |
| Worker integration | `backend/tests/integration` | real worker loop, deterministic fake providers |
| Browser E2E | `e2e/` | Playwright, fake providers, small local media fixtures |
| Real-provider smoke | marked `real_provider` | opt-in, nightly/manual, real models |

* Tests requiring a real model or the network are marked `@pytest.mark.real_provider` and
  are **deselected by default**. Never make default CI depend on a live YouTube video.
* Fake providers are deterministic by construction — same input, byte-identical output.
* Prefer asserting on observable behaviour (artifact exists, duration within tolerance,
  state transition happened) over asserting on internal call sequences.
* Do not write tests solely to move a coverage number.

---

## 7. Working on the pipeline

Stages are registered handlers in `worker/handlers/`, wired by the planner into a
persisted dependency graph. To add or change a stage:

1. Define/extend the port in `application/ports/`.
2. Write the deterministic fake first, plus its contract test.
3. Implement the handler; it must be **idempotent by input hash** — if a valid artifact
   for the same input hash exists, reuse it.
4. Declare what the stage invalidates in the invalidation graph. Getting this wrong is the
   most common source of stale-output bugs.
5. Add the real provider behind an optional dependency group, last.

Never let a stage depend on the wall-clock ordering of another stage; depend on persisted
artifacts.

---

## 8. Frontend rules

* TypeScript strict. No `any` escape hatches in feature code.
* API types are **generated** from the backend OpenAPI schema into `src/api/generated/`.
  Never hand-write a backend enum or DTO. A stale generated client fails CI.
* Server state lives in TanStack Query. Component-local visual state stays local. No
  global store until real complexity justifies one.
* Native, accessible HTML controls first. The segment editor must be keyboard-navigable.

---

## 9. When you are unsure

* A decision that is cheap to reverse: make it, note it in the commit body, move on.
* A decision that is expensive to reverse: write it in `questions.md` with the options and
  your recommendation, implement the reversible option, and open an ADR when it is settled.
* A question that should be answered by measurement, not argument (model quality, timing
  tolerance, performance): put it in `questions.md` as an experiment, not a debate.

Do not silently expand scope. English→German, one narrator, Linux, local browser.
