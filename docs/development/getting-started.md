# Development workflow

Install Python 3.12, Node 20.19 or newer, `uv`, `pnpm`, FFmpeg, and `yt-dlp`, then run:

```bash
make install
make check
make dev
```

Open `http://127.0.0.1:5173`. `scripts/dev` starts the API and worker first, waits for API
health, then starts Vite. `Ctrl-C` stops all three processes.

The default configuration selects installed local providers and falls back where possible.
Run `make doctor` to see the exact tools and providers available. Real translation and TTS
stacks are optional:

```bash
make install-providers
make test-real
```

## Deterministic browser test

```bash
cd e2e
pnpm exec playwright install chromium
cd ..
make test-e2e
```

The E2E server creates a temporary 15-second video and isolated data directory, selects all
fake providers, and removes the runtime directory when it exits. No network source, model,
GPU, or committed media fixture is involved.

## API contract changes

After changing a route or schema, regenerate and commit the browser types:

```bash
make openapi
```

`make check` runs the same generator in comparison mode and fails when the committed schema
is stale.
