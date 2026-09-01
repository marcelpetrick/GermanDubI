#!/usr/bin/env bash
# The single quality gate for GermanDubI, run identically by a developer and by CI.
#
# CI calls this script rather than repeating its steps, so the two cannot drift: if this
# passes on a clean checkout, CI passes, and the reverse holds too.
#
# It assumes only the documented prerequisites (see README): git, a C toolchain-free
# Python provisioned by uv, Node.js with corepack, ffmpeg and yt-dlp.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

# --------------------------------------------------------------------------- options
run_e2e=1
run_build=1
run_smoke=1

usage() {
  cat <<'USAGE'
usage: ./localPipeline.sh [options]

  --no-e2e     Skip the Playwright browser workflow (and its browser download).
  --no-build   Skip building the wheel and the production browser bundle.
  --no-smoke   Skip the production server smoke test.
  --fast       Quality gates only: no build, no browser, no smoke test.
  -h, --help   Show this message.

With no options every stage runs, which is what CI does.
USAGE
}

while (($#)); do
  case "$1" in
    --no-e2e) run_e2e=0 ;;
    --no-build) run_build=0 ;;
    --no-smoke) run_smoke=0 ;;
    --fast)
      run_e2e=0
      run_build=0
      run_smoke=0
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

# --------------------------------------------------------------------------- output
if [[ -t 1 ]]; then
  bold=$'\033[1m' red=$'\033[31m' green=$'\033[32m' dim=$'\033[2m' reset=$'\033[0m'
else
  bold='' red='' green='' dim='' reset=''
fi

stage_names=()
stage_times=()
pipeline_started=$SECONDS

stage() {
  echo
  echo "${bold}==> $*${reset}"
  stage_started=$SECONDS
  current_stage="$*"
}

stage_done() {
  local elapsed=$((SECONDS - stage_started))
  stage_names+=("$current_stage")
  stage_times+=("$elapsed")
  echo "${dim}    ${current_stage} took ${elapsed}s${reset}"
}

# --------------------------------------------------------------------------- providers
# The gate installs exactly the locked default set, which means `uv sync` *uninstalls* any
# optional provider extra that was there. Left alone, running the gate turns a machine that
# could dub into one that cannot, silently -- it caught this project's own maintainer twice,
# and being documented in three places was evidence of the surprise rather than a fix.
#
# So: note what is installed before the sync, and put it back on the way out. Restoring
# happens on every exit path, including a failed gate and Ctrl-C, because a gate that fails
# is exactly when someone is least likely to notice their providers are gone.
#
# The gate itself still runs against the lean set. That is the point of it: the deterministic
# fakes are what make the run reproducible, and a machine with the extras installed must not
# pass a gate that a clean checkout would fail.
declare -A extra_of=(
  [faster-whisper]=asr
  [argostranslate]=translate
  [piper-tts]=tts
  [demucs]=separation
)
providers_to_restore=()

note_installed_providers() {
  local installed dist
  installed="$(uv pip list --format=freeze 2>/dev/null || true)"
  for dist in "${!extra_of[@]}"; do
    if grep -q "^${dist}==" <<<"$installed"; then
      providers_to_restore+=("--extra" "${extra_of[$dist]}")
    fi
  done
}

restore_providers() {
  ((${#providers_to_restore[@]})) || return 0
  echo
  echo "${bold}==> Restoring the provider extras this gate removed${reset}"
  if uv sync --locked --all-groups "${providers_to_restore[@]}"; then
    echo "${dim}    the machine can dub again${reset}"
  else
    echo "${red}    could not restore them; run: make install-providers${reset}" >&2
  fi
}

# --------------------------------------------------------------------------- cleanup
# Every exit path tears the smoke-test server down, including Ctrl-C and a failed gate.
server_pid=""
smoke_dir=""

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  [[ -n "$smoke_dir" && -d "$smoke_dir" ]] && rm -rf "$smoke_dir"
  restore_providers

  echo
  if ((status == 0)); then
    echo "${green}${bold}pipeline passed${reset} in $((SECONDS - pipeline_started))s"
    local index=0
    while ((index < ${#stage_names[@]})); do
      printf '%s    %-26s %5ss%s\n' "$dim" "${stage_names[index]}" "${stage_times[index]}" "$reset"
      index=$((index + 1))
    done
  else
    echo "${red}${bold}pipeline failed${reset} during: ${current_stage:-startup}"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

# --------------------------------------------------------------------------- prerequisites
stage "Checking prerequisites"
# The same script `make setup` runs, so a machine that can install this project is exactly
# a machine that can run its gate. Two copies of this list would drift.
./scripts/preflight
stage_done

# --------------------------------------------------------------------------- setup
stage "Locked dependencies"
note_installed_providers
# --locked fails rather than silently resolving something new, so a stale lockfile is a
# pipeline failure instead of an unreproducible pass.
uv sync --locked --all-groups
if ((${#providers_to_restore[@]})); then
  echo "${dim}    provider extras removed for the run; they are restored at the end${reset}"
fi
(cd frontend && pnpm install --frozen-lockfile)
(cd e2e && pnpm install --frozen-lockfile)
stage_done

# --------------------------------------------------------------------------- gates
stage "Generated API client"
./scripts/generate-client --check
stage_done

stage "Formatting and linting"
uv run ruff format --check backend scripts
uv run ruff check backend scripts
(cd frontend && pnpm run lint)
(cd frontend && pnpm exec prettier --check ../e2e)
stage_done

stage "Type checking"
uv run mypy
(cd frontend && pnpm run typecheck)
(cd e2e && pnpm run typecheck)
stage_done

stage "Backend tests"
# The coverage floor lives in pyproject.toml and fails the run on its own.
uv run pytest --cov --cov-report=term-missing
stage_done

stage "Frontend tests"
(cd frontend && pnpm run test)
stage_done

# --------------------------------------------------------------------------- build
if ((run_build)); then
  stage "Building distributions"
  uv build
  (cd frontend && pnpm run build)
  stage_done
fi

# --------------------------------------------------------------------------- e2e
if ((run_e2e)); then
  stage "Deterministic browser"
  # --with-deps installs system packages and therefore needs root. That is correct on a
  # clean CI runner and wrong on a developer machine, where it fails on a sudo password
  # prompt that no script should ever trigger. Ask for system dependencies only where we
  # can actually install them; the browser download itself never needs privileges.
  if [[ -n "${CI:-}" || "$(id -u)" == "0" ]]; then
    (cd e2e && pnpm exec playwright install --with-deps chromium)
  else
    (cd e2e && pnpm exec playwright install chromium)
  fi
  stage_done

  stage "Browser workflow"
  (cd e2e && pnpm run test)
  stage_done
fi

# --------------------------------------------------------------------------- smoke
# Building a wheel proves it compiles; this proves the built artifacts actually serve.
if ((run_smoke)); then
  if ((run_build)) && [[ -d frontend/dist ]]; then
    stage "Production smoke test"
    smoke_dir="$(mktemp -d)"
    port=8757

    GERMANDUBI_DATA_DIR="$smoke_dir/data" \
      GERMANDUBI_PORT="$port" \
      uv run germandubi serve --port "$port" >"$smoke_dir/server.log" 2>&1 &
    server_pid=$!

    ready=0
    for _ in $(seq 1 100); do
      if ! kill -0 "$server_pid" 2>/dev/null; then
        echo "${red}the server exited during startup${reset}" >&2
        cat "$smoke_dir/server.log" >&2
        exit 1
      fi
      if curl -fsS "http://127.0.0.1:$port/api/v1/health" >/dev/null 2>&1; then
        ready=1
        break
      fi
      sleep 0.2
    done
    if ((ready == 0)); then
      echo "${red}the server did not become healthy${reset}" >&2
      cat "$smoke_dir/server.log" >&2
      exit 1
    fi

    curl -fsS "http://127.0.0.1:$port/api/v1/health" | grep -q '"status"'
    # The compiled bundle must be served, not just built.
    curl -fsS "http://127.0.0.1:$port/" | grep -qi '<div id="root"'
    echo "    health and the compiled bundle both served on port $port"
    stage_done
  else
    echo
    echo "${dim}==> Skipping the smoke test: it needs the build stage${reset}"
  fi
fi
