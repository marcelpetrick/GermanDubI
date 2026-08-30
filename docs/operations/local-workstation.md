# Local workstation operation

Project data defaults to `$XDG_DATA_HOME/germandubi`, or
`~/.local/share/germandubi` when `XDG_DATA_HOME` is unset. Override it with
`GERMANDUBI_DATA_DIR`. Do not point this at the repository or commit its contents.

For development, use `make dev`. For a production-like local process:

```bash
make build
GERMANDUBI_FRONTEND_DIST="$PWD/frontend/dist" uv run germandubi serve
uv run germandubi worker
```

The API binds to loopback by default. If it is exposed beyond the local machine, put it
behind an authenticated reverse proxy; the `0.x` API does not provide multi-user auth.

Creating a release is documented separately in [`releasing.md`](releasing.md), and common
failures in [`troubleshooting.md`](troubleshooting.md).

Useful diagnostics:

```bash
make doctor
uv run germandubi list
uv run germandubi inspect PROJECT_ID
```

Generated media remains inside the project's artifact workspace. Source files and previous
revisions are not overwritten. Back up the data directory as one unit so SQLite metadata
and artifact files stay consistent.
