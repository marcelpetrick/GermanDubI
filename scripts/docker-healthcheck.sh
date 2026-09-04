#!/bin/sh
# What "healthy" means depends on which of the two programs this container is running.
#
# The image ships one entrypoint and two commands. `serve` answers HTTP; `worker` does not
# and never will. A single HTTP probe therefore reported every worker container as
# unhealthy forever -- `docker ps` showed it, and so did `docker compose up`, where it also
# blocks anything that waits on `service_healthy`.
#
# The subcommand is read from PID 1, which is `tini -- germandubi <command> [...]`.
set -eu

command_of_pid_1() {
    tr '\0' '\n' < /proc/1/cmdline \
        | grep -vxE '(/usr/bin/)?tini|--|(.*/)?germandubi' \
        | head -n 1
}

case "$(command_of_pid_1)" in
    worker)
        # The worker has no socket to answer on, and a worker whose process has died takes
        # the container with it, so liveness is already covered. What can fail while the
        # process stays up is the data volume -- a mount whose ownership does not match the
        # container's user leaves the worker unable to write a single artifact, which is a
        # real failure that otherwise only shows up as stages failing one by one.
        exec python -c 'import os, pathlib, sys
data = pathlib.Path(os.environ.get("GERMANDUBI_DATA_DIR", "/data"))
probe = data / ".healthcheck"
try:
    probe.write_bytes(b"")
    probe.unlink()
except OSError as exc:
    print(f"{data} is not writable: {exc}", file=sys.stderr)
    sys.exit(1)
'
        ;;
    *)
        exec python -c 'import os, sys, urllib.request
port = os.environ.get("GERMANDUBI_PORT", "8756")
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=4) as answer:
    sys.exit(0 if answer.status == 200 else 1)
'
        ;;
esac
