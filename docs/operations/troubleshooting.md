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
make install-providers      # recognition, translation and German speech
germandubi doctor           # confirm before starting a long run
```

Note that `uv sync --locked` -- run by `make install` and by `./localPipeline.sh` -- removes
the optional extras again, so reinstall them after running the gate.

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
the original instead of removing the narration. This is the documented fallback. Install
the extra for real separation:

```bash
uv sync --extra separation      # large; a GPU is strongly preferred
```

**A segment is rushed or clipped.** The German is longer than the English it replaces.
Segments that could not be fitted within the configured limits are flagged rather than
forced; review them in the browser and shorten the German text.

**Every phrase appears two or three times in the segments.** Fixed in 0.1.1. Scrolling
captions restate each finished line in the following cue, and those repeats were being
treated as new speech. Re-run the project to rebuild its transcript.

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

**Real providers disappear after running the gate.** `uv sync --locked` installs exactly
the locked default set, which excludes the optional extras. Reinstall them:

```bash
make install-providers
```

## Where the data is

```bash
make doctor                       # prints the resolved data directory
uv run germandubi list            # projects, newest first
uv run germandubi inspect ID      # stages, state and segment counts for one project
```

Project media, the SQLite database, and downloaded models all live under the data
directory. Back it up as one unit; the database and the artifact files must stay
consistent with each other.
