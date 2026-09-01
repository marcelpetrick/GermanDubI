# Troubleshooting

Start with `make doctor`. It reports which external tools are on `PATH`, which provider
backs each port, whether each is a local or a network provider, and whether the data
directory is writable. Most problems below are visible there first.

## Analysis fails immediately

**"the source site returned metadata this version cannot read"**
Historically this meant captured output was truncated before it could be parsed; that is
fixed. If it recurs, the source genuinely returned something unparseable -- run the probe
by hand to see it:

```bash
yt-dlp --dump-single-json --skip-download 'URL' | head -c 400
```

**"the source requires signing in" / "the video is private" / "age-restricted"**
GermanDubI does not circumvent access controls and will not attempt to. Use a source you
can access anonymously, or supply the file yourself as a local path.

**"could not read \<file\>"**
The local file is not media, or is truncated. `ffprobe <file>` will say the same thing more
verbosely.

## The run fails with "no ... provider is installed"

This is deliberate. Translation and speech have no usable substitute: the placeholder
providers append "ung" to English words and emit a quiet tone, so a run using them finishes
and contains no German. The error names the command:

```bash
make setup                  # from a clean checkout: everything, then a doctor report
make install-providers      # recognition, translation, German speech and separation
germandubi doctor           # confirm before starting a long run
```

Note that `uv sync --locked` -- run by `make install` -- removes the optional extras again,
so reinstall them afterwards. `./localPipeline.sh` also removes them, because the gate runs
against deterministic fakes on purpose, but it notices what was there and puts it back when
it exits.

## The dub sounds wrong

**The German is not German at all** -- text like "fuer Manyung Yearsung" and audio that is a
quiet tone rather than speech. That is the placeholder output of a run made without the real
providers. Versions before 0.1.1 selected the placeholders silently and reported success;
install the providers and re-run the project.

**The German is obviously machine-literal.** Check which transcript provider ran. Automatic
captions are unpunctuated, and translation quality depends heavily on punctuation:

```
using speech recognition for the English transcript          good
falling back to the source's automatic captions              expect worse German
```

Installing the ASR extra (`uv sync --extra asr`) moves a source with only automatic
captions onto the recognition path.

**The German plays over the English.** No separation model is installed, so the mix ducks
the original instead of removing the narration. This is the documented fallback.
`make install-providers` includes separation; if you installed the extras by hand, add it:

```bash
uv sync --extra separation
```

**A segment is rushed or clipped.** The German is longer than the English it replaces.
Segments that could not be fitted within the configured limits are flagged rather than
forced; review them in the browser and shorten the German text.

**Every phrase appears two or three times in the segments.** Fixed in 0.1.1. Scrolling
captions restate each finished line in the following cue, and those repeats were being
treated as new speech. Re-run the project to rebuild its transcript.

## A stage sits at 100% CPU and then fails with a time limit

`adelay` into `amix` intermittently deadlocks in FFmpeg n9.0.1: the process spins at full
CPU and never produces a frame. It reproduces roughly half the time on narration assembly
graphs, and it is an FFmpeg fault rather than a GermanDubI one -- the same command run by
hand hangs the same way.

Nothing is lost when it happens. The process runner's timeout kills the stage and the
worker retries it, and because the deadlock is intermittent the retry usually succeeds. The
visible symptom is one slow stage, not a failed project. If a stage exhausts its retries,
re-running the pipeline resumes from the last finished stage.

## Adding a second video while one is being dubbed

Supported, and queued rather than parallel. One worker processes one stage at a time, so
the second video starts once the first finishes -- except for inspecting the source, which
jumps the queue so a newly pasted URL is analysed within a stage or two rather than after
the whole dub.

The second project's page says where it stands: "Waiting for another project to finish",
with its position when more than one is queued. The position is read from the same ordering
the worker claims in, so it is the real wait rather than a guess.

Versions before 0.2.1 returned `500 Internal Server Error` here, twice for different
reasons. The worker first held the database for the length of every stage; then, after that
was fixed, reporting progress took the write lock and held it for the work that followed --
"using faster-whisper" was announced, and the lock stayed taken for the two minutes of
recognition. Both are fixed. Upgrading is the answer; no setting helps.

If it recurs, the log names the failure. See below.

## Where the server log is

```
~/.local/share/germandubi/logs/germandubi.log
```

`make doctor` prints the exact path, which honours `XDG_DATA_HOME` and
`GERMANDUBI_DATA_DIR`. It rotates at 5 MB and keeps three older files, and it is written in
addition to the console, so a failure survives closing the terminal.

An unexpected failure in the browser shows a reference like `Reference a1b2c3d4` along with
this path. Find the failure by that reference:

```bash
grep -A 40 a1b2c3d4 ~/.local/share/germandubi/logs/germandubi.log
```

Set `GERMANDUBI_LOG_FILE` to write it elsewhere, or to `none` for console-only logging.
`GERMANDUBI_LOG_LEVEL=DEBUG` turns up the detail. A destination that cannot be written --
a read-only volume, a full disk -- falls back to the console rather than stopping the
server.

## Stopping a run, and clearing everything

**Stop** appears next to a project that is working, and on the project's own page. It
terminates the tool currently running rather than waiting for it to finish, keeps every
stage that already completed, and the run can be resumed afterwards.

**Delete everything** removes every project and all generated files from this machine,
after asking. It cancels anything still running first, so a stage cannot recreate the
directory it was just deleted from. It cannot be undone.

## Nothing happens after pressing Create German Dub

The worker is not running. `make dev` starts it alongside the API; if you started only the
API, start it separately:

```bash
uv run germandubi worker
```

Jobs are persisted, so a worker started later picks up the queued run.

## The gate fails but the code looks fine

**Frontend tests fail to load with `markAsUncloneable is not a function`.** The Node
runtime is too old. Use the pinned version:

```bash
fnm use        # or: nvm use
```

`./localPipeline.sh` checks this before running anything.

**Prettier fails on `e2e/test-results/...`.** Generated Playwright output is ignored; if
this reappears, a new generated path needs adding to `frontend/.prettierignore`.

**`uv sync --locked` fails.** The lockfile does not match `pyproject.toml`. Run
`uv lock` and commit the result.

**Real providers disappear after `make install`.** `uv sync --locked` installs exactly the
locked default set, which excludes the optional extras. Reinstall them:

```bash
make install-providers
```

`./localPipeline.sh` restores them itself, on every exit path including a failed run and
Ctrl-C. If that restore fails it says so and names this command.

## Where the data is

```bash
make doctor                       # prints the resolved data directory
uv run germandubi list            # projects, newest first
uv run germandubi inspect ID      # stages, state and segment counts for one project
```

Project media, the SQLite database, and downloaded models all live under the data
directory. Back it up as one unit; the database and the artifact files must stay
consistent with each other.
