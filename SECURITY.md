# Security Policy

## Reporting

Report suspected vulnerabilities privately to <mail@marcelpetrick.it>. Please do not open
a public issue for an unfixed vulnerability. Include a description of the problem class,
affected version (`GET /api/v1/meta` or `germandubi version`), and reproduction steps.
Please do not include working exploit code.

## Threat model for `0.x`

GermanDubI is a **local-first, single-user workstation application**. It binds to
`127.0.0.1` by default and has no authentication. Exposing the API to a network is
outside the supported configuration for `0.x`.

The two genuinely untrusted inputs are the **source URL** and the **downloaded media**.

## Input handling rules

* Only `https` source URLs are accepted.
* Only known, explicitly allowlisted YouTube hostnames are accepted.
* URLs carrying embedded credentials are rejected.
* `file://`, `localhost`, loopback, link-local and private-network targets are rejected.
* Arbitrary downloader or FFmpeg arguments are never accepted from the UI.
* Generated filenames are sanitized; all downloaded data stays inside the project workspace.
* Every artifact path is resolved and verified to remain under the project root before it
  is opened or served (path-traversal defence).

## External processes

All external programs (`ffmpeg`, `ffprobe`, `yt-dlp`) are invoked through one central
process runner using **argument arrays, never a shell**, with timeouts, cancellation,
bounded output capture and process-tree termination.

## Rights, DRM and voice identity

* GermanDubI does not implement, and will not accept contributions implementing, DRM or
  access-control circumvention.
* Users are responsible for holding the rights to process and redistribute source content.
* Voice **identity cloning** is a separate, optional capability that requires explicit
  recorded authorization for the voice being reproduced. It is deliberately not part of
  the default pipeline.

## Dependency and secret scanning

CI runs a Python dependency audit and a frontend dependency audit. Secrets are never
stored in project JSON; provider credentials come from environment variables.
