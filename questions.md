# questions.md — Open design and architecture questions

Every unresolved decision lives here. Each entry states the question, why it matters, the
options, and — where one was needed to keep moving — the **provisional answer** currently
implemented. A provisional answer is a reversible bet, not a settled decision.

When a question is resolved: mark it `RESOLVED`, record the outcome, and write an ADR in
`docs/adr/` if the decision is expensive to reverse.

Status values: `OPEN` · `PROVISIONAL` (implemented, revisit) · `EXPERIMENT` (answer by
measurement) · `RESOLVED`.

---

## A. Product and scope

### Q-A1 — Is the local-file input path in scope for the MVP, or URL only? · `PROVISIONAL`

`vision.md` §5.1 lists local file input "shortly after the URL vertical slice".
A local file is also by far the easiest way to run the pipeline offline and in tests.

**Provisional:** both are supported from the start. `SourceRef` is a sum type
(`YouTubeSource` | `LocalFileSource`); the URL path is the headline feature, the local-file
path is what CI and the fixtures exercise. Cost of supporting both is one extra
acquisition adapter.

### Q-A2 — What is "done" for the MVP? · `PROVISIONAL`

**Provisional:** paste a YouTube URL (or pick a local file) → analyze → create German dub
→ preview in the browser → edit a German segment → regenerate just that segment → export
an MKV with a German audio track, the original audio track, and DE+EN subtitles. Anything
beyond that is post-MVP.

### Q-A3 — Should the MVP ship a "reduce original voice" fallback when no separation model is installed? · `PROVISIONAL`

Full source separation (Demucs) is a large optional dependency.

**Provisional:** yes. The default mix strategy is **ducking** — attenuate the original
audio under German speech segments — which needs only FFmpeg and always works. Real stem
separation is an optional upgrade, selected automatically when installed.
Revisit after Q-C3.

### Q-A4 — How does the user express "this segment is approved"? Does approval survive regeneration? · `OPEN`

Approval is per segment, but a segment can be invalidated by an upstream edit. Options:
(a) approval is cleared on any invalidation; (b) approval sticks to a specific revision and
is shown as "approved, but the source has changed since". (b) is more informative and more
work. Currently (a).

---

## B. Domain and data model

### Q-B1 — What exactly is the boundary of a dubbing segment? · `EXPERIMENT`

Sentence, caption cue, breath group, or fixed max duration? This drives translation
quality (context), timing (fit), and review ergonomics (how many rows the user scans).

**Provisional:** sentence-based segmentation with a max duration and a min duration,
merging short fragments and splitting over-long sentences at clause boundaries.
**Experiment:** measure duration-mismatch rate and reviewer edit count per strategy on the
reference clip.

### Q-B2 — Are segment boundaries user-editable in the MVP (split/merge)? · `PROVISIONAL`

Split/merge invalidates translation and speech for the affected segments and renumbers
ordinals, which complicates the invalidation graph.

**Provisional:** not in the MVP. Text is editable; boundaries are not. The domain model is
built to support it (`split`/`merge` operations exist and are property-tested) so it can be
exposed later without a data migration.

### Q-B3 — How are overlapping or zero-length source cues normalized? · `PROVISIONAL`

Auto-generated YouTube captions routinely overlap and repeat.

**Provisional:** a canonicalization pass enforces `start < end`, strict ordering and
non-overlap, clipping the earlier cue. Property-tested. **Open:** whether clipping or
merging produces better German output.

### Q-B4 — Should `Word` be persisted for every word, or only when alignment is available? · `PROVISIONAL`

Word rows dominate table size (a 20-minute video is ~3000 words).

**Provisional:** persist words; SQLite handles this volume easily and word timing is what
makes accurate re-segmentation possible later.

### Q-B5 — What is the project format version policy for `0.x`? · `OPEN`

`vision.md` §34 separates project format version from application version. Unresolved: do
we support opening an older project format, or refuse with a clear message? Currently a
mismatch is refused with an explicit error. Migration of on-disk manifests is not
implemented.

---

## C. Machine learning providers

### Q-C1 — Captions or ASR by default? · `EXPERIMENT`

`vision.md` §74.1. YouTube automatic captions are free and instant but unpunctuated,
sometimes wrong, and their timing is coarse. ASR costs minutes of GPU/CPU but gives clean
punctuation and word timestamps.

**Provisional:** prefer **manual** captions when detectable; otherwise run ASR; use
automatic captions only when ASR is unavailable. **Experiment:** compare WER and downstream
translation quality on the reference clip.

### Q-C2 — Which alignment provider gives acceptable English word timing? · `EXPERIMENT`

Candidates: WhisperX forced alignment, `faster-whisper` word timestamps, an aeneas-style
classical aligner. **Provisional:** `faster-whisper` word timestamps, because it removes a
whole dependency stack when ASR is already running.

### Q-C3 — Which separation model best removes narration while retaining music? · `EXPERIMENT`

Candidates: Demucs (htdemucs), MDX-Net, Open-Unmix. Judged on residual-voice audibility and
music damage, not on SDR alone.

### Q-C4 — Which local EN→DE translation provider? · `EXPERIMENT`

Candidates: Argos Translate (light, CPU, ~100 MB), Helsinki-NLP `opus-mt-en-de` via
transformers (better, needs torch), NLLB-200 (best, heavy), or an LLM with a
duration-constrained prompt (best at *shortening*, but non-deterministic and possibly
network). **Provisional:** Argos Translate as the default local provider because it is
CPU-only and small; the port allows swapping without touching application code.

### Q-C5 — Which German TTS backend? · `EXPERIMENT`

Candidates: Piper (fast, CPU, permissive, good German "Thorsten" voices), Coqui XTTS
(better prosody and voice cloning, heavier, license constraints), a network TTS API.
**Provisional:** Piper. It is the only candidate that is realistically CPU-realtime on a
workstation, which the review/regenerate loop depends on.

### Q-C6 — How much duration mismatch can be fixed acoustically before it sounds bad? · `EXPERIMENT`

German is typically 10–30 % longer than English. Options in order of preference: retranslate
shorter → adjust TTS speaking rate → time-stretch the audio → borrow silence from
neighbouring pauses → let the segment overrun.

**Provisional bounds, to be validated by listening:** time-stretch limited to ±8 %, TTS rate
to ±15 %, and anything still over +15 % is flagged for the user rather than forced.

### Q-C7 — Are explicit prosody features worth it versus just matching rate and pauses? · `EXPERIMENT`

`vision.md` §74.7. **Provisional:** MVP matches speaking rate and pause structure only.

### Q-C8 — Do we ever send data to a network provider by default? · `RESOLVED`

**No.** All default providers are `LOCAL`. A `NETWORK` provider must be selected explicitly
and the UI must state what leaves the machine. See ADR-0010.

---

## D. Architecture and infrastructure

### Q-D1 — At what point does SQLite job claiming become a limitation? · `EXPERIMENT`

`vision.md` §74.10. With one worker it is a non-issue. **Provisional:** single worker,
transactional claim with a lease. Measure claim contention when a second worker is added.

### Q-D2 — How are jobs cancelled mid-stage? · `PROVISIONAL`

**Provisional:** cooperative cancellation. The API sets `CANCEL_REQUESTED`; the worker polls
at stage checkpoints and, for external processes, terminates the process tree. A stage that
ignores cancellation for a long time is a bug in that stage.

### Q-D3 — Should the worker run stages in-process or fork per stage? · `OPEN`

ML stacks with conflicting CUDA/torch requirements may eventually force process isolation
per provider (`vision.md` §24.1). Currently in-process. The port boundary means a
subprocess-backed provider can be introduced without touching application code.

### Q-D4 — SSE reconnection and event replay semantics? · `PROVISIONAL`

**Provisional:** events are persisted with a monotonic sequence number; the client sends
`Last-Event-ID` and the server replays from there. Retention of the event log is unbounded
today — needs a policy.

### Q-D5 — Where does user project data live by default? · `PROVISIONAL`

`vision.md` §41 says it should default outside the Git checkout.
**Provisional:** `$XDG_DATA_HOME/germandubi` (falling back to `~/.local/share/germandubi`),
overridable by `GERMANDUBI_DATA_DIR`. The in-repo `data/` directory is for development only.

### Q-D6 — Should the API serve media previews itself, or hand out file paths? · `PROVISIONAL`

**Provisional:** the API serves media with HTTP range support, so nothing outside the
workspace is ever exposed and the browser gets seeking. Must never load a file fully into
memory.

### Q-D7 — Preview transcoding: which codecs actually play in the browser? · `EXPERIMENT`

`vision.md` §74.8. YouTube commonly yields VP9/Opus in WebM (fine in Chrome/Firefox) or
AV1 (patchy). **Provisional:** try direct playback; transcode a preview proxy on demand
when the browser cannot play the source.

---

## E. Process, tooling and release

### Q-E1 — Python version floor? · `PROVISIONAL`

**Provisional:** `>=3.12,<3.14`. 3.12 is the floor because the ML dependency stack
(torch, faster-whisper, ctranslate2) lags new releases; 3.14 is excluded for the same
reason. Revisit when the optional ML groups support it.

### Q-E2 — Squash or rebase merges? · `PROVISIONAL`

**Provisional:** rebase and fast-forward, keeping the atomic commits. Squashing would
destroy the per-commit version trace that `setuptools-scm` gives us.

### Q-E3 — Coverage floor? · `PROVISIONAL`

**Provisional:** 80 % repository-wide as a diagnostic, with domain and application logic
expected to be far higher. Coverage is not a goal in itself (`vision.md` §28).

### Q-E4 — License? · `RESOLVED`

**Decision:** GermanDubI is licensed under GPL-3.0-or-later; see ADR-0011. Optional ML
dependencies and model assets retain their own licenses and are not redistributed as part
of this repository. Provider-specific license metadata remains visible at the boundary.

### Q-E5 — Do we publish to PyPI? · `OPEN`

Affects package naming and whether the frontend build must be bundled into the wheel.
Currently the wheel is built in CI but not published.

---

## F. Questions inherited from `vision.md` §74

| # | Question | Tracked as |
| --- | --- | --- |
| 1 | Captions vs. ASR reliability | Q-C1 |
| 2 | Alignment provider quality | Q-C2 |
| 3 | Best separation model | Q-C3 |
| 4 | Correctable duration mismatch | Q-C6 |
| 5 | Best local translation provider | Q-C4 |
| 6 | Best German TTS backend | Q-C5 |
| 7 | Prosody features vs. rate/pauses | Q-C7 |
| 8 | Browser-playable preview codecs | Q-D7 |
| 9 | GPU/RAM baseline for Balanced | Q-G1 |
| 10 | SQLite job-claiming limits | Q-D1 |

---

## G. Performance

### Q-G1 — What hardware baseline should the `Balanced` quality profile assume? · `EXPERIMENT`

Needs measurement of the processing factor (processing time ÷ video duration) per stage on
CPU-only versus a mid-range GPU. Until measured, `Balanced` targets CPU-only operation so
the MVP runs everywhere.

### Q-G2 — Acceptable processing factor for the MVP? · `OPEN`

A 20-minute video taking 20 minutes (1.0×) is tolerable for a workstation tool; 5× is not.
No target is committed until Q-G1 is measured per stage.
