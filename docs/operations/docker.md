# Running GermanDubI in a container

Nothing to build, nothing to clone:

```bash
docker volume create germandubi-data
docker run -d --name germandubi-api -p 127.0.0.1:8756:8756 \
  -v germandubi-data:/data ghcr.io/marcelpetrick/germandubi serve
docker run -d --name germandubi-worker \
  -v germandubi-data:/data ghcr.io/marcelpetrick/germandubi worker
```

Then open <http://127.0.0.1:8756>. Two containers from one image: the API answers the
browser, the worker does the dubbing, and they find each other through the shared volume.

From a checkout, `docker compose up` does the same thing in one command.

---

## What you need on the host

**Docker. That is the entire list.** No Python, no Node, no `ffmpeg`, no GPU, no account —
all of it is inside the image, and the image runs on any machine with a Docker daemon.

Two things are named elsewhere on this page and neither is required:

- **The Compose plugin** is what provides the `docker compose` subcommand. It only matters
  if you use `compose.yaml`; the two `docker run` commands above are the same thing written
  out. If `docker compose version` says the command is unknown, install
  `docker-compose-plugin` (Debian/Ubuntu) or `docker-compose` (Arch). Docker Desktop on
  macOS and Windows already has it.
- **The NVIDIA Container Toolkit** maps a GPU and its driver libraries into a container. It
  is needed only for the GPU worker below. The published image is CPU-only and never asks
  for it.

## Using it once it is running

Open <http://127.0.0.1:8756>. Everything below happens in the browser; nothing needs a
terminal.

1. **Paste a YouTube URL and press Analyze.** The source is inspected without downloading
   it, so within a second or two you see the title, the length, and whether it has English
   captions. Pick the German narrator from the dropdown first if you want a particular
   voice — press play beside one to hear it.
2. **Press Create German dub.** Sixteen stages run in order and the screen follows them.
   Roughly a fifth of the video's running time on a CPU, so a 40-minute source is about
   eight minutes. You can close the tab: progress is saved and the run continues.
3. **Review the segments.** Every segment shows the English, the German, and how well the
   German fits the original timing. Filter to *Flagged* to see only the ones that need
   attention.
4. **Correct anything wrong.** Edit the German text and press *Save German & regenerate*.
   Only that segment is spoken again, plus the mixing and export that depend on it —
   transcription and separation are not repeated. Your edit is never overwritten by a later
   run.
5. **Approve and download.** Approving every segment completes the project. *Download
   export* gives you the video with the German dub, the original audio kept as a second
   track, and German and English subtitles.

Add another URL at any time, including while a dub is running. One video is processed at a
time and the rest queue; a waiting project says so and shows its position.

### From the command line instead

The same image runs the CLI, against the same volume:

```bash
docker exec germandubi-api germandubi doctor      # what is installed, where data lives
docker exec germandubi-api germandubi list        # projects, newest first
docker exec germandubi-api germandubi inspect ID  # one project's stages and segments
```

To dub without the browser at all — useful for scripting, and it prints a stack trace when
something fails:

```bash
docker run --rm -v germandubi-data:/data \
  ghcr.io/marcelpetrick/germandubi dub 'https://www.youtube.com/watch?v=...'
```

To dub a file from your own disk, mount the directory it is in:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" -e HOME=/data \
  -v ~/Videos:/in:ro -v germandubi-data:/data \
  ghcr.io/marcelpetrick/germandubi dub /in/lecture.mp4
```

The first dub is slower than the rest: the recognition, translation, speech and separation
models download once, into the volume, and are reused afterwards.

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

Docker stores images and build layers under its data root, which is `/var/lib/docker` by
default and may not be on the partition with the space. Moving it is supported and is a
`daemon.json` setting;
[moving-the-docker-data-root.md](moving-the-docker-data-root.md) records doing it on this
project's development machine, with the checks that made it safe.

`lean` exists to try the interface, to review someone else's finished project, or to check
that the container works at all without waiting for a multi-gigabyte download. It reports
"Not ready to dub" from `germandubi doctor`, which is correct and deliberate: a run that
quietly produced no German would be worse.

```bash
PROVIDERS=lean docker compose build
```

The message that build prints — "Install them with `make install-providers`" — is advice
for a source checkout. In a container the answer is to rebuild without `PROVIDERS=lean`.

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

## Sharing it with someone

They need Docker and one command. If the image is published, that is `docker run` as above.
For a machine with no access to the registry, hand over a file:

```bash
docker pull ghcr.io/marcelpetrick/germandubi          # or build it yourself
docker save ghcr.io/marcelpetrick/germandubi | zstd -o germandubi.tar.zst
```

```bash
zstd -d < germandubi.tar.zst | docker load
```

658 MB compressed, measured, from a 2.26 GB export. `gzip` works too and is slower and
larger. The round trip was verified: `docker load` restores the image under its own tag.

## Publishing it

### The three registries worth being on

| | Host | Why |
| --- | --- | --- |
| **Docker Hub** | `docker.io` | The default. `docker pull marcelpetrick/germandubi` needs no registry prefix, and it is where people look first. Rate-limits anonymous pulls. |
| **GitHub Container Registry** | `ghcr.io` | Sits beside the source. No pull rate limit, no second account, and the workflow authenticates with a token GitHub already provides. |
| **Quay.io** | `quay.io` | Red Hat's, and what the Kubernetes and RHEL world reaches for. Free public repositories. |

There is no reason to choose. The workflow publishes the same digests under all
three, so a single build ends up everywhere and the manifests point at identical bytes.

### Automatically, on a version tag

`.github/workflows/image.yml` runs on the same tag that cuts a release. It builds
`linux/amd64` and `linux/arm64` on runners of each architecture — never under QEMU, which
takes hours for a stack with torch in it — and merges them into one manifest list, so
`docker pull` picks the right architecture without anyone choosing.

**GHCR needs no setup.** The workflow uses the token GitHub provides. One manual step,
once: the package starts private, so open the repository's *Packages* section and set its
visibility to public.

**Docker Hub** — five minutes, once:

1. Create the repository `germandubi` under your account at
   <https://hub.docker.com/repositories>. Make it public.
2. *Account settings → Personal access tokens* → **New access token**, description
   `github-actions`, permissions **Read & Write**. Copy it; it is shown once.
3. In GitHub, *Settings → Secrets and variables → Actions → New repository secret*:
   - `DOCKERHUB_USERNAME` = `marcelpetrick`
   - `DOCKERHUB_TOKEN` = the token from step 2

**Quay.io** — the same shape:

1. Create the repository `germandubi` at <https://quay.io/new/>, visibility public.
2. *Account settings → Robot accounts* → create one with **Write** on that repository.
   Quay shows the robot's username as `marcelpetrick+github_actions` and its token.
3. Add `QUAY_USERNAME` and `QUAY_TOKEN` as GitHub secrets.

Each registry is skipped silently when its secrets are absent, so nothing breaks in a fork
and you can add them one at a time.

Use tokens, never your account password: a token is scoped to what it can push and can be
revoked on its own if it leaks.

### By hand

Same result, if you would rather not wait for a tag. Build once, tag it for each place:

```bash
make docker-build                       # germandubi:latest, version from the current tag
VERSION=0.3.0

docker login -u marcelpetrick                                    # Docker Hub
docker tag germandubi:latest marcelpetrick/germandubi:$VERSION
docker tag germandubi:latest marcelpetrick/germandubi:latest
docker push marcelpetrick/germandubi:$VERSION
docker push marcelpetrick/germandubi:latest
```

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u marcelpetrick --password-stdin
docker tag germandubi:latest ghcr.io/marcelpetrick/germandubi:$VERSION
docker push ghcr.io/marcelpetrick/germandubi:$VERSION
```

```bash
docker login quay.io -u marcelpetrick
docker tag germandubi:latest quay.io/marcelpetrick/germandubi:$VERSION
docker push quay.io/marcelpetrick/germandubi:$VERSION
```

A hand-built push is single-architecture — whatever machine you built on. Only the workflow
produces the amd64 + arm64 manifest, so an Apple Silicon user pulling a hand-pushed amd64
image gets emulation. Worth knowing before you push `latest` by hand.

### Being found

The image carries the standard `org.opencontainers.image.*` annotations — title,
description, authors, vendor, source, documentation, version, licence. All three registries
read them to fill in the listing, and `docker inspect` shows them to anyone who wants to
know what they just pulled. The maintainer is named as
**Marcel Petrick &lt;mail@marcelpetrick.it&gt;**, which is who a registry or a user contacts
about the image.

Two fields the registries do **not** take from the image, worth setting once per repository.

**Short description** — one line, shown in search results. The same one the GitHub
repository uses, because it earns its place:

```
Like Dobby, the house-elf, but for dubbing — a local-first workstation that turns an English video into an editable, synchronized German dub.
```

**Long description** — the page body, rendered as Markdown on Docker Hub and Quay. Paste
this:

````markdown
# GermanDubI

**Like Dobby, the house-elf, but for dubbing.** Paste an English video URL, press *Analyze*,
press *Create German Dub*, and get an editable, synchronized German dub — with every
intermediate stage inspectable and reproducible.

**Nothing leaves your machine** except the URL you paste. Recognition, translation, speech
and separation all run locally. No account, no API key, no upload.

## Run it

```bash
docker volume create germandubi-data
docker run -d --name germandubi-api -p 127.0.0.1:8756:8756 \
  -v germandubi-data:/data marcelpetrick/germandubi serve
docker run -d --name germandubi-worker \
  -v germandubi-data:/data marcelpetrick/germandubi worker
```

Open <http://127.0.0.1:8756>. Two containers from one image: the API answers the browser,
the worker does the dubbing, and they share the `/data` volume — projects, database,
models and log all live there.

## What you get

- **A dub you can correct.** Every segment shows the English, the German and how well the
  German fits the original timing. Fix a translation and only that segment is spoken again,
  plus what depends on it — transcription and separation are not repeated.
- **A pipeline, not a script.** Sixteen stages with recorded inputs, outputs and
  provenance. Close the tab, restart the machine; a run resumes from the last finished
  stage.
- **Subtitles too.** German and English, alongside a video that keeps the original audio as
  a second track.
- **Your language.** Interface in English, Deutsch, Hrvatski and 中文. Dark and light
  themes.

## Tags

| Tag | |
| --- | --- |
| `latest`, `X.Y.Z` | Every provider, CPU-only. `linux/amd64` and `linux/arm64`. |

Roughly a fifth of the video's running time on a CPU: a 40-minute source takes about eight
minutes. The models download once, into the volume, on the first dub.

## More

- Source, issues and full documentation:
  <https://github.com/marcelpetrick/GermanDubI>
- Container guide — GPU, configuration, bind mounts, offline sharing:
  <https://github.com/marcelpetrick/GermanDubI/blob/main/docs/operations/docker.md>
- Licence: GPL-3.0-or-later
- Maintainer: Marcel Petrick &lt;mail@marcelpetrick.it&gt;
````

Docker Hub can keep that in step automatically — `peter-evans/dockerhub-description` reads a
file from the repository on each push to `main`. Worth adding once the description settles;
until then, pasting it is a two-minute job done rarely.

Tag deliberately: `latest` should only ever move on a real release. The workflow enforces
this — a manual run publishes `0.0.0-dev` and leaves `latest` alone.

## Building for another architecture

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t germandubi .
```

Needs the `buildx` plugin. The Dockerfile itself uses no BuildKit-only syntax, so a plain
`docker build` with the classic builder works too — deliberately, because requiring buildx
would stop some people building at all.

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

**Not verified here**: `docker compose up`, on a host with no Compose plugin; the GPU
profile, on a host with no NVIDIA container runtime; and the publish workflow, which can
only be exercised by running it. The compose file parses, and the two commands its services
run are the ones exercised directly above.

**Verified separately**: the offline path. `docker save | zstd` produced a 658 MB file from
a 2.26 GB export, and `docker load` restored the image from it.

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
