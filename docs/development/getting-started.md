# Development workflow

Four things must be on the machine already: `uv`, Node 24 with `corepack`, and
`ffmpeg`/`ffprobe`. `uv` provisions the Python pinned in `.python-version`; corepack
provisions `pnpm`; everything else -- including `yt-dlp` and the JavaScript challenge solver
it needs -- is a declared dependency and is installed for you.

```bash
make setup          # preflight, dependencies, every real provider, hooks, then `doctor`
make check          # fast inner loop: lint, types, tests
make dev
```

`make preflight` is the check on its own. Both `make setup` and `./localPipeline.sh` run it
first, from one script, so a machine that can install this project is exactly a machine that
can run its gate.

An older Node appears to work and then fails obscurely: the frontend test stack needs an API
that Node 20 does not have, so every test file fails to load. Preflight catches it and says
so.

Open `http://127.0.0.1:5173`. `scripts/dev` starts the API and worker first, waits for API
health, then starts Vite. `Ctrl-C` stops all three processes.

The default configuration selects installed local providers and falls back where possible.
Run `make doctor` to see the exact tools and providers available. Real translation and TTS
stacks are optional:

```bash
make install-providers  # just the providers, if the rest is already there
make test-real
```

Neither the gate nor CI installs them: both run against deterministic fakes, and a machine
with the real stacks must not pass a gate a clean checkout would fail. The gate therefore
removes them for the duration -- and restores whatever it found when it exits, so running it
does not leave you unable to dub. `make install` has no such courtesy; reinstall after it
with `make install-providers`.

They are not optional in practice: without a translator and a German voice the pipeline
refuses to run rather than producing placeholder output, and `germandubi doctor` will say
so. Separation still has a working fallback -- without it the mix ducks the original audio
instead of removing it -- but it is installed by default now, because a dub that leaves the
English voice faintly audible is not the result most people want.

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
