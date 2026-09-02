# Running GermanDubI in a container

One command, no toolchain to install:

```bash
docker compose up
```

Then open <http://127.0.0.1:8756>. That is the whole thing: `compose.yaml` builds the image
on first run, starts the API and the worker, and keeps every project in a named volume.

Everything else on this page is detail you only need when something is unusual.

---

## What you need on the host

Docker, and nothing else. No Python, no Node, no `ffmpeg` — all three live inside the image.

`docker compose` is the Compose v2 plugin. If `docker compose version` says the command is
unknown, install `docker-compose-plugin` (Debian/Ubuntu) or `docker-compose` (Arch); Docker
Desktop on macOS and Windows ships it already.

## Two images, and which one you want

| Build | Image size | Can it dub? |
| --- | --- | --- |
| default | **2.4 GB** | Yes — recognition, translation, German speech, separation, on the CPU |
| `TORCH=cuda` | about 5 GB | Yes, and can use an NVIDIA GPU |
| `PROVIDERS=lean` | 814 MB | No — every stage runs, and the output is placeholder tones, not German |

**The default image is CPU-only, and that is the whole difference between 2.4 GB and 5 GB.**
The locked resolution installs the CUDA build of torch, which drags in 2.8 GB of NVIDIA
libraries. Inside a container those are reachable only through the NVIDIA Container Toolkit,
and on macOS they are dead weight that can never be used. The build swaps torch for the CPU
wheel and deletes them, in the same layer, so neither the image nor the build ever carries
them.

Build with `--build-arg TORCH=cuda` when you want the GPU worker. Nothing else changes.

`lean` exists to try the interface, to review someone else's finished project, or to check
that the container works at all without waiting for a multi-gigabyte download. It reports
"Not ready to dub" from `germandubi doctor`, which is correct and deliberate: a run that
quietly produced no German would be worse.

```bash
PROVIDERS=lean docker compose build
```

The message that build prints — "Install them with `make install-providers`" — is advice
for a source checkout. In a container the answer is to rebuild without `PROVIDERS=lean`.

## Without compose

```bash
docker build -t germandubi .
docker volume create germandubi-data

docker run -d --name germandubi-api \
  -p 127.0.0.1:8756:8756 -v germandubi-data:/data germandubi serve
docker run -d --name germandubi-worker \
  -v germandubi-data:/data germandubi worker
```

Two containers from one image. They must share the volume: that directory is how they find
each other.

## Stamping the version

The image cannot read Git — the build context deliberately excludes `.git` — so the version
is passed in. `make docker-build` derives it from the current tag; plain `docker compose up`
does not, and the resulting image reports `0.0.0`. To get a real version from compose, put
it in a `.env` beside `compose.yaml`:

```bash
echo "GERMANDUBI_VERSION=$(git describe --tags --dirty | sed 's/^v//')" > .env
```

Cosmetic for running it, and worth doing before sharing an image with anyone, because
`germandubi version` and the interface footer are how you tell two builds apart.

## Where your work lives

Everything is in the `germandubi-data` volume, mounted at `/data`:

```
/data/projects/<id>/   media, audio stems, per-segment speech, the export
/data/germandubi.db    projects, segments, runs, events
/data/models/          downloaded models, cached after first use
/data/logs/            the server log
```

That volume is the only thing worth backing up, and the only thing to delete to start over:

```bash
docker compose down -v          # removes the volume too. This cannot be undone.
```

To keep projects on your own filesystem instead of in a Docker volume, bind-mount a
directory. The container runs as UID 10001, which will not match you, so either hand the
directory to that UID:

```bash
mkdir -p ~/germandubi-data && sudo chown 10001:10001 ~/germandubi-data
docker run -d -p 127.0.0.1:8756:8756 -v ~/germandubi-data:/data germandubi serve
```

or run as yourself, which needs no `sudo` and leaves files you own:

```bash
mkdir -p ~/germandubi-data
docker run -d -p 127.0.0.1:8756:8756 \
  --user "$(id -u):$(id -g)" -e HOME=/data \
  -v ~/germandubi-data:/data germandubi serve
```

`HOME` is set because an arbitrary UID has no entry in the image's password file, and some
libraries look there for a cache directory.

## Using a GPU

Separation measured 3.6× faster on a GPU than on a CPU over a 120-second sample, and
recognition benefits similarly. It needs the [NVIDIA Container
Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/) on the
host.

```bash
docker compose --profile gpu up api worker-gpu
```

Do not run `worker` and `worker-gpu` at the same time. One worker per data directory is
enforced — the second refuses to start and says so — but there is no reason to make it
prove that.

## Which hosts this works on

| Host | Works | GPU |
| --- | --- | --- |
| Linux, x86-64 | Yes | Yes, with the NVIDIA Container Toolkit |
| Windows, x86-64 (Docker Desktop, WSL2) | Yes | Yes, through WSL2 with the toolkit |
| macOS, Apple Silicon | Yes, built for arm64 | No — CUDA does not exist on macOS, and Metal is not reachable from a Linux container |
| macOS, Intel | Yes | No |

A container is a Linux container everywhere, which is why one image serves all three hosts.
Two caveats worth stating plainly:

- **Apple Silicon needs an arm64 build.** The default `docker build` on that machine
  produces one. Pulling an x86-64 image instead runs it under emulation, where a dub is
  slow enough not to be worth doing.
- **macOS has no GPU path.** Not a packaging problem, and not fixable here: the ML stacks
  target CUDA, and a Linux VM cannot reach Metal. Dubbing on a Mac is CPU work.

## Building for another architecture

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t germandubi .
```

Needs the `buildx` plugin. The Dockerfile itself uses no BuildKit-only syntax, so a plain
`docker build` with the classic builder works too — deliberately, because requiring buildx
would stop some people building at all.

## Settings

Every `GERMANDUBI_*` setting works as it does outside a container. The ones that matter here:

| Variable | In the image | Why |
| --- | --- | --- |
| `GERMANDUBI_DATA_DIR` | `/data` | The volume |
| `GERMANDUBI_HOST` | `0.0.0.0` | Binds inside the container; what the outside can reach is decided by port publishing |
| `GERMANDUBI_PORT` | `8756` | |
| `GERMANDUBI_FRONTEND_DIST` | `/app/frontend/dist` | The API serves the browser bundle; no second web server |
| `GERMANDUBI_DEVICE` | `auto` | `cuda` when one is usable, `cpu` otherwise |
| `HF_HOME` | `/data/models/huggingface` | Model downloads survive `docker rm` |

**The published port is loopback on purpose.** `compose.yaml` binds
`127.0.0.1:8756`, because this is a single-user workstation tool with no authentication of
any kind. Changing that to `0.0.0.0` puts an unauthenticated service that downloads URLs
and runs `ffmpeg` on your network.

## When something goes wrong

```bash
docker compose logs -f worker      # the pipeline talks here
docker compose logs -f api
docker compose exec api germandubi doctor
docker compose exec api germandubi list
```

The server log is also a file inside the volume, at `/data/logs/germandubi.log`, and an
unexpected error in the browser quotes a reference that appears in it. See
[troubleshooting.md](troubleshooting.md).

`docker stop` gives the worker 120 seconds to finish what it is doing. That is deliberate: a
stage can be minutes inside one `ffmpeg` or Demucs call, and the worker has a clean shutdown
path that keeps finished stages. Killing it sooner is safe — work is resumable — but it
throws away whatever that stage had not committed.

## What has and has not been exercised

Stated plainly, because a container that has never been run is a guess:

**Verified**, on both images, with the classic builder:

- Builds, reports the version it was stamped with, serves the browser bundle over HTTP,
  answers `/api/v1/health`, and reaches Docker's own `healthy` state.
- `germandubi doctor` finds `ffmpeg`, `ffprobe`, `yt-dlp` and a JavaScript runtime.
- A second worker against a shared volume is refused with the right message. The advisory
  lock is a kernel lock on one inode, so it works across containers — which is what makes
  the two-service layout in `compose.yaml` safe.

**Verified on the default image only**, because the lean one cannot do it: a real dub, end
to end. Twenty seconds of English narration went in and fourteen of fifteen stages
succeeded, including recognition, separation, translation and German speech —
"For many years, archaeologists puzzled over…" came back as "Viele Jahre lang rätselten
Archäologen darüber…", with German and English subtitle files and synthesized speech beside
it. The fifteenth stage refused correctly: the input was a bare `.wav`, and there is no
video to mux a dub into.

**Not verified here**: `docker compose up`, on a host with no Compose plugin, and the GPU
profile, on a host with no NVIDIA container runtime. The compose file parses, and the two
commands its services run are the ones exercised directly above.

## What the image contains

Three build stages, so the runtime carries nothing a build needed:

1. **frontend** — Node builds the browser bundle.
2. **python-build** — `uv sync --locked` resolves the same versions the lockfile pins, into
   `/opt/venv`.
3. **runtime** — Python slim, plus `ffmpeg`, plus `tini`, plus the `node` binary copied from
   the first stage. `yt-dlp` needs a JavaScript runtime to solve YouTube's challenge, and
   Debian's own Node is much older than the one this project pins.

It runs as UID 10001, not root: a dub writes gigabytes of intermediate audio, and root-owned
files on your volume are a nuisance you would have to clean up with `sudo`.

`tini` is PID 1 so the `ffmpeg`, `yt-dlp` and Demucs children a stage leaves behind are
reaped, and so `SIGTERM` reaches the worker rather than the shell that started it.
