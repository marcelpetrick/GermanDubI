# GermanDubI

**German Dub Interface** — English YouTube videos to German ones, made easy.

GermanDubI is a local-first, browser-based video dubbing workstation. Paste an English
video URL, press *Analyze*, press *Create German Dub*, and get an editable, synchronized
German dub while every intermediate stage stays inspectable and reproducible.

> The full product vision and technical architecture live in [`vision.md`](vision.md).
> Ways of working live in [`AGENTS.md`](AGENTS.md).
> Unresolved design decisions live in [`questions.md`](questions.md).

---

## What it does

```text
YouTube URL
    ↓  probe → acquire → normalize
    ↓  captions or ASR → forced alignment → dubbing segments
    ↓  EN→DE translation → duration fitting → German TTS
    ↓  voice/background separation → mix → QA
    ↓
German-dubbed MKV/MP4 (+ DE/EN subtitles, original audio track kept)
```

The first target is deliberately narrow: **English source, German target, one dominant
narrator, Linux host, local browser UI.**

---

## Status

Early development (`0.x`). The project format and HTTP API are still evolving.
See [`CHANGELOG.md`](CHANGELOG.md) for what exists today.

---

## Requirements

| Requirement | Notes |
| --- | --- |
| Linux | Primary and only supported host for `0.x` |
| Python (see `pyproject.toml`) | Managed by [`uv`](https://docs.astral.sh/uv/) |
| Node.js 20+ with `corepack` | Frontend toolchain, `pnpm` is provisioned by corepack |
| `ffmpeg` / `ffprobe` | Media inspection, extraction, muxing |
| `yt-dlp` | Source acquisition |

Run `germandubi doctor` at any time to check the environment.

---

## Quick start

```bash
git clone https://github.com/marcelpetrick/GermanDubI.git
cd GermanDubI

uv sync --all-groups          # backend environment
corepack enable pnpm          # frontend package manager
make install                  # frontend dependencies

make check                    # formatting, lint, types, tests — must pass on a clean checkout
make dev                      # API + Vite dev server + processing worker
```

Then open the URL printed by the Vite dev server.

---

## Repository layout

```text
backend/    Python modular monolith (domain / application / infrastructure / api / worker / cli)
frontend/   React + TypeScript + Vite single-page app
e2e/        Playwright end-to-end tests
docs/       Architecture, ADRs, development and operations documentation
scripts/    Thin wrappers used by the Makefile
data/       Default local project storage (never committed)
```

---

## Developer commands

| Command | Purpose |
| --- | --- |
| `make dev` | Run API, frontend and worker together |
| `make check` | Approximate the full CI pipeline locally |
| `make test` | Run the whole test suite |
| `make lint` / `make format` | Ruff + ESLint/Prettier |
| `make typecheck` | `mypy --strict` and `tsc --noEmit` |
| `make version` | Print the VCS-derived build version |

---

## Licensing and rights

GermanDubI is released under the [MIT License](LICENSE).

The software does not circumvent access controls or DRM. **Users are responsible for
holding the rights to process and redistribute any source content**, and for holding
authorization for any voice they reproduce. See [`SECURITY.md`](SECURITY.md).
