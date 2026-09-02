# GermanDubI in a container.
#
# Three stages: build the browser bundle with Node, resolve the Python environment with uv,
# and copy both into a slim runtime that carries nothing a build needs. The result runs the
# API and the worker from the same image -- `germandubi serve` and `germandubi worker` --
# so compose starts two containers from one build rather than needing a supervisor inside
# one container.
#
#   docker build -t germandubi .                       # everything, ~5 GB
#   docker build -t germandubi --build-arg PROVIDERS=lean .   # no models, ~700 MB
#
# Deliberately free of BuildKit-only syntax: no dockerfile-frontend directive, no cache
# mounts. It therefore builds with the classic builder as well. Cache mounts would shorten a
# rebuild and would cost anyone without the buildx plugin the ability to build at all, which
# is the wrong trade for a tool whose whole point is that you run it yourself.
#
# See docs/operations/docker.md.

# --------------------------------------------------------------------------- arguments
# Kept at the top so every stage can see them. Pinned by digest-free tag on purpose: the
# lockfiles pin what actually matters, and a base image tag that never moves would go
# unpatched.
ARG NODE_IMAGE=node:24.20.0-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# --------------------------------------------------------------------------- frontend
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build

# Manifests first: the dependency layer is then reused whenever only source changed, which
# is most of the time.
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN corepack enable pnpm && pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm run build

# --------------------------------------------------------------------------- python
FROM ${PYTHON_IMAGE} AS python-build

# Which provider stacks to install. `full` is every real model -- recognition, translation,
# German speech and separation -- and is what makes the image able to actually dub. `lean`
# is the same application without them, useful for trying the interface or for a machine
# that will only ever review someone else's output.
ARG PROVIDERS=full

# setuptools-scm derives the version from Git, and the build context has no .git. Passing it
# in keeps the image honest about which version it is instead of reporting 0.0.0.
ARG VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_GERMANDUBI=${VERSION}

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY backend/ ./backend/

# --no-editable because the source tree does not survive into the runtime stage, and an
# editable install would leave a .pth file pointing at a directory that is not there.
RUN if [ "${PROVIDERS}" = "lean" ]; then \
        uv sync --locked --no-dev --no-editable; \
    else \
        uv sync --locked --no-dev --no-editable \
            --extra asr --extra translate --extra tts --extra separation; \
    fi

# --------------------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="GermanDubI" \
      org.opencontainers.image.description="Turn English videos into editable German dubs." \
      org.opencontainers.image.source="https://github.com/marcelpetrick/GermanDubI" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

# ffmpeg is the only external tool the pipeline requires. Everything else it needs -- yt-dlp
# and its JavaScript challenge solver -- is a Python dependency and arrives with the venv.
RUN apt-get update && apt-get install --yes --no-install-recommends \
        ffmpeg \
        tini \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp cannot get formats from YouTube without solving a JavaScript challenge, and needs a
# runtime to do it. Taken from the Node stage rather than from Debian, which ships a much
# older Node: both images are bookworm, so the binary matches the C library here.
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node

COPY --from=python-build /opt/venv /opt/venv
COPY --from=frontend /build/dist /app/frontend/dist

# A dub writes gigabytes of intermediate audio. Running as root would leave every one of
# those files owned by root on the host's volume.
RUN useradd --create-home --uid 10001 germandubi \
    && mkdir -p /data \
    && chown -R germandubi:germandubi /data /app

ENV PATH="/opt/venv/bin:${PATH}" \
    GERMANDUBI_DATA_DIR=/data \
    GERMANDUBI_FRONTEND_DIST=/app/frontend/dist \
    # Bind to every interface *inside the container*. What the outside world can reach is
    # decided by the port publishing, which compose limits to loopback.
    GERMANDUBI_HOST=0.0.0.0 \
    GERMANDUBI_PORT=8756 \
    # Model downloads land in the data volume, so they survive `docker rm` and are not
    # re-downloaded on every container start.
    HF_HOME=/data/models/huggingface \
    XDG_CACHE_HOME=/data/cache \
    PYTHONUNBUFFERED=1

USER germandubi
WORKDIR /app
VOLUME ["/data"]
EXPOSE 8756

# tini reaps the ffmpeg, yt-dlp and Demucs children a stage leaves behind, and forwards
# SIGTERM so `docker stop` reaches the worker's own clean-shutdown path instead of killing
# it mid-write.
ENTRYPOINT ["/usr/bin/tini", "--", "germandubi"]
CMD ["serve"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['GERMANDUBI_PORT']}/api/v1/health\", timeout=4).status==200 else 1)"]
