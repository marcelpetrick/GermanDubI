# Development workflow

Install `uv`, FFmpeg and `yt-dlp`, plus the runtimes pinned in `.python-version` and
`.node-version` (Python 3.12 and Node 24). `corepack` provisions `pnpm`. Then run:

```bash
make install
make check          # fast inner loop: lint, types, tests
make dev
```

An older Node appears to work and then fails obscurely: the frontend test stack needs an
API that Node 20 does not have, so every test file fails to load. `./localPipeline.sh`
checks this before doing anything else.

Open `http://127.0.0.1:5173`. `scripts/dev` starts the API and worker first, waits for API
health, then starts Vite. `Ctrl-C` stops all three processes.

The default configuration selects installed local providers and falls back where possible.
Run `make doctor` to see the exact tools and providers available. Real translation and TTS
stacks are optional:

```bash
make install-providers
make test-real
```

Neither the gate nor CI installs them, so `uv sync --locked` removes them again. Reinstall
with `make install-providers` after running the pipeline.

They are not optional in practice: without a translator and a German voice the pipeline
refuses to run rather than producing placeholder output, and `germandubi doctor` will say
so. Only separation is genuinely optional -- without it the mix ducks the original audio
instead of removing it.

## Verifying a real dub

Every gate above runs against deterministic fakes, which proves nothing about the product
itself. To take a real source through the whole path with real providers and measure it:

```bash
make install-providers
./scripts/benchmark_real_dub.py --excerpt-seconds 120
./scripts/benchmark_real_dub.py --full
```

See [`docs/benchmarks/`](../benchmarks/) for what the last run measured.

## The full gate

`make check` is the inner loop. Before pushing, run the complete pipeline -- the same
script CI runs, so a green run here means a green run there:

```bash
./localPipeline.sh          # or: make pipeline
./localPipeline.sh --fast   # gates only: no build, browser or smoke test
```

It checks prerequisites, installs from the lockfiles, runs every gate, builds both
distributions, runs the browser workflow, and smoke-tests the production server.

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
