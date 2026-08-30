# Real-source measurements

Every automated gate in this repository runs against deterministic fake providers. That is
the right choice for CI -- it is fast, offline and reproducible -- but it proves nothing
about the product. A fake cannot show that a real download, a real transcript, real German
speech and a real mix combine into a file someone can play.

These measurements are the counterpart to that. They come from
[`scripts/benchmark_real_dub.py`](../../scripts/benchmark_real_dub.py), which drives the
real pipeline with real providers on a real source and records what it cost.

```bash
make install-providers
./scripts/benchmark_real_dub.py --excerpt-seconds 120   # quick, repeatable
./scripts/benchmark_real_dub.py --full                  # the whole source
```

The script refuses to run if any port resolves to a placeholder provider, so a result here
always reflects real work. Stage timings are read from the pipeline's own persisted job
records rather than from a stopwatch wrapped around the call.

## Files

| File | What it holds |
| --- | --- |
| `real-dub.json` | The bounded 120-second excerpt run |
| `real-dub-full.json` | The complete 40-minute source |

The dubbed video itself is written to `benchmark-output/` and is deliberately not
committed: the measurements belong in Git, a 30 MB video does not.

## Reference source

[`f3r05guSo1w`](https://www.youtube.com/watch?v=f3r05guSo1w) — 40 minutes of English
narration with one dominant narrator, which is exactly the case GermanDubI targets first.
It is a useful reference precisely because it is unexceptional: it exposed three separate
defects that no fake had, in metadata size, in word ordering, and in word timing.

## Reading a result

`realtime_factor` is the ratio of work to source length: 0.30 means 36 seconds of
processing for 120 seconds of video, so a dub costs roughly a third of the time it would
take to watch. Below 1.0 is faster than realtime.

Numbers are from one machine and one provider set. They are for comparing runs and
spotting regressions, not for promising anything about other hardware. The host and the
selected providers are recorded in each file for exactly that reason.

Where the time goes is more durable than the absolute totals: transcription dominates when
speech recognition runs, and synthesis is the next largest. Stages that only move bytes --
extracting audio, assembling, mixing -- are noise by comparison.
