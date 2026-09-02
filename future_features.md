# Where GermanDubI could go next

Written 2026-09-02, against v0.3.0. Twenty-two ideas, each with what it is worth and what it
would cost, plus a list of things deliberately not worth building.

The point of the market section is not to copy anyone. It is to be honest about which of
this project's weaknesses a user will actually notice, and which of its strengths nobody
else has.

---

## What else exists

**Cloud, paid, voice-cloning first.** HeyGen, ElevenLabs Dubbing, Rask AI, Papercup,
Deepdub. They dub into dozens of languages, clone the original speaker's voice, and some do
lip sync. They are good, they are convenient, and every second of source audio is uploaded
to somebody else's machine. Pricing is per minute of video, so a back catalogue is
expensive.

**Open source, closest peers.** SoniTranslate (Gradio, Whisper + TTS + Demucs),
VideoLingo (strong on subtitle segmentation and translation quality), Linly-Dubbing. They
are capable and they are scripts with a UI bolted on: one long run, no resumability, no
artifact provenance, and a correction means running the whole thing again.

**Subtitle-first tools.** Subtitle Edit is twenty years mature and does one thing
extremely well. Many people who want a dub would in fact be happy with good subtitles, and
some of them do not know it yet.

### What this project already has that none of them do

- **Nothing leaves the machine** except the source URL. That is a category difference, not
  a feature, and it is the one thing a cloud service structurally cannot offer.
- **A dependency graph, not a script.** Sixteen stages with recorded inputs and outputs, so
  correcting one segment re-runs synthesis onward for that segment and nothing else. This
  is what makes a 500-segment review pass survivable.
- **Every intermediate kept, with provenance.** Which provider, which model, which input
  hash produced each artifact.
- **A review loop that is actually a loop.** Edit the German, the speech is regenerated,
  the mix is rebuilt. Working today, covered end to end by a browser test.

### What a user will notice is missing

In roughly the order they will notice it:

1. **One voice for everybody.** A documentary with three speakers gets one narrator.
2. **The German is stilted.** Argos is a small offline model, and it shows on idiom.
3. **German only.** The name says so, and it is still the first question people ask.
4. **The original speaker's voice is gone.** Replaced, not preserved.

---

## Ideas

Impact is about what a user would feel. Effort is rough calendar weeks for one person.

### Output quality — what people hear

* [ ] **[High impact / 2-3 weeks] Give each speaker their own voice.**
  A documentary with a narrator and two interviewees is currently read by one voice, which
  flattens exactly the thing that made the original watchable. Speaker diarization is a
  solved local problem and the segment model already has room for the label.
  *Do:* add a `diarize` stage between `separate` and `segment` using `pyannote.audio`,
  store `speaker_id` on the segment, and map speakers to voices round-robin from the
  installed Piper set with a per-project override in the review UI. Note that the better
  pyannote checkpoints are gated behind a Hugging Face token, which conflicts with
  "installs without an account" -- check the licence before adopting one.

* [ ] **[High impact / 2-3 weeks] Replace Argos with a local LLM translator.**
  Argos is a small CTranslate2 model and it is the weakest link in the finished dub: it
  renders idiom literally and has no way to be told "this must fit in 3.2 seconds". The
  `TranslationRequest` already carries `preceding`, `following`, `glossary` and
  `max_characters`, and Argos ignores all four.
  *Do:* a second `TranslationProvider` over llama.cpp or Ollama with a prompt that uses the
  context and the character budget. The port exists, so this touches one new file plus
  registry selection. Keep Argos as the no-GPU fallback; measure both on the same source
  before switching the default.

* [ ] **[High impact / 1 week] Retranslate instead of time-stretching when the German runs long.**
  Seventy of five hundred segments in a recent real run still overran after fitting, which
  is where a dub starts sounding rushed. Asking for a shorter sentence is better than
  speeding up the one you have.
  *Do:* when `fit` flags an overrun beyond the threshold, re-request the translation with a
  tighter `max_characters` and re-synthesize, up to two attempts. Needs the LLM translator
  above to be worth anything, because Argos cannot honour a budget.

* [ ] **[Medium impact / 1 week] Normalise loudness on export.**
  The German narration is mixed at whatever level the voice produced, so one dub is quiet
  and the next is hot. A user noticed this on the first real run: "the german audio is too
  silent".
  *Do:* an `ffmpeg loudnorm` two-pass to a stated target on the export stage, -16 LUFS for
  streaming or -23 for broadcast, and put the measured figure in the QA report.

* [ ] **[Medium impact / 2 weeks] Preserve the original speaker's voice.**
  The single most-requested thing in this category, and the most dangerous. Local voice
  cloning is now feasible on a workstation GPU.
  *Do:* a `TTSProvider` over a local cloning model (F5-TTS, Chatterbox, XTTS and successors).
  Gate it behind explicit consent per project, refuse it without an affirmative flag, and
  read every candidate model's licence carefully -- several are non-commercial, which a
  GPL-3.0 tool must not quietly redistribute or imply permission for.

* [ ] **[Low impact / 3 days] Carry emphasis and pauses across, not just timing.**
  The prosody stage measures rate and pauses and only the rate is used. A narrator's beat
  before a punchline is currently thrown away.
  *Do:* feed the measured pause structure into the synthesis request as SSML-style breaks
  where the voice supports it, and into the fit stage as preferred split points.

### Reach — what it can be pointed at

* [ ] **[High impact / 2 weeks] More than one target language.**
  The pipeline is language-agnostic apart from hardcoded `en`/`de` in the providers and a
  handful of labels. Every person shown this asks the same question in the first minute.
  *Do:* make source and target languages project fields, drive Argos/Piper/Whisper
  selection from them, and keep German the default. The domain already carries
  `source_language` and `target_language`; they are just never anything else.

* [ ] **[Medium impact / 1 week] Dub something that is not on YouTube.**
  Local files already work through the CLI and are unreachable from the browser, which is
  where everyone starts.
  *Do:* a file picker and a drag-and-drop target on the home page, posting `file_path` to
  the endpoint that already accepts it. Add a directory watch for people with a backlog.

* [ ] **[Medium impact / 1 week] Batch a whole playlist or folder.**
  Anyone with a back catalogue wants to point this at fifty videos and come back tomorrow.
  The queue already handles this; nothing exposes it.
  *Do:* accept a playlist URL or a directory, create one project per item, and show the
  queue with positions. Most of the machinery landed with the queue-position work.

* [ ] **[Low impact / 3 days] Subtitles as a first-class output.**
  A meaningful share of people who want a dub would be satisfied by good German subtitles,
  which this produces already and treats as a side effect.
  *Do:* offer the SRT/VTT files as their own download, and let a project stop at
  `subtitle` without synthesizing anything -- much faster, much cheaper, and honest about
  what it is.

### The review loop — where the time actually goes

* [ ] **[High impact / 1 week] Fill in the glossary.**
  `TranslationRequest.glossary` is implemented, applied case-insensitively on word
  boundaries, and tested -- and nothing ever puts anything in it, so it is always empty.
  Names and technical terms therefore drift across a long video.
  *Do:* a per-project glossary table and a small editor in the review screen, passed into
  the request the handler already builds. This is the cheapest real quality win on the list.

* [ ] **[High impact / 1-2 weeks] Make review keyboard-driven.**
  Reviewing 500 segments with a mouse is the actual cost of using this tool. The filters
  help; the interaction does not.
  *Do:* `j`/`k` to move, space to play the segment, `a` to approve, `n` to jump to the next
  flagged one, `/` to search. Show the shortcuts. Nothing here needs a backend change.

* [ ] **[Medium impact / 1-2 weeks] A/B the German against the original.**
  A reviewer cannot currently hear what the original said without leaving the tool, so
  judging a translation means trusting the transcript.
  *Do:* a second play button per segment for the master audio at that interval, and a
  waveform strip showing where the German sits inside the slot.

* [ ] **[Medium impact / 4 days] Round-trip subtitles through Subtitle Edit.**
  Some people are simply faster in a tool they have used for years, and refusing to
  interoperate does not make them use this one.
  *Do:* export the German segments as SRT and accept a corrected SRT back, matching on
  timing and creating a `USER_EDIT` revision per changed cue. The revision history already
  models this.

* [ ] **[Medium impact / 3 days] Bulk actions.**
  Approving 430 unflagged segments one at a time is the difference between a review pass
  that finishes and one that does not.
  *Do:* approve-all-unflagged, retranslate-all-flagged, and a confirmation naming the
  count. The per-segment endpoints exist; this is a loop and a dialog.

* [ ] **[Low impact / 2 days] Show why a segment was flagged.**
  A badge reading "runs long" does not say by how much or what the tool did about it.
  *Do:* on the selected segment, show the measured deviation, the stretch applied and the
  budget it missed. The numbers are all on the segment already.

### Operating it

* [ ] **[High impact / 1 week] Estimate how long a run will take.**
  "Processing" with a bar at 30% for fifteen minutes is indistinguishable from a hang, and
  a user hit exactly that.
  *Do:* record per-stage seconds per source-minute in the events table -- they are already
  logged -- and show a projection from this machine's own history rather than a guess.

* [ ] **[Medium impact / 1 week] Report progress from inside a long stage.**
  Assembly reports once and then says nothing for a quarter of an hour, which is also why
  its lease expires underneath it.
  *Do:* pass a progress callback into `concatenate_speech` and report per batch, which
  also renews the lease and gives cancellation a checkpoint to land on.

* [ ] **[Medium impact / 4 days] Move a project between machines.**
  A dub represents hours of compute and there is no way to take it anywhere -- to a
  colleague, to a backup, to a faster box.
  *Do:* export a project as one archive of its rows and its workspace, and import it back.
  The format version field on the project exists for exactly this.

* [ ] **[Low impact / 2 days] Prune what a finished project no longer needs.**
  A 40-minute dub leaves gigabytes of stems, per-segment audio and staging files. One
  recent run left 4.6 GB of intermediates for 500 clips.
  *Do:* a per-project "reclaim space" action that removes regenerable artifacts and keeps
  the export, the transcript and the segment text, saying how much it freed.

* [ ] **[Low impact / 3 days] Show what produced this.**
  Provenance is recorded on every artifact -- provider, model, input hash, app version --
  and there is no way to look at it.
  *Do:* a per-artifact panel behind the artifact count already shown on the preview card.
  Useful for arguments about whether a re-run would change anything.

### Reaching people

* [ ] **[High impact / 1 week] Run it from a container.**
  In progress. "Install uv, Node 24, ffmpeg, then run make setup" loses people who would
  otherwise use this.
  *Do:* see `docs/operations/docker.md`.

* [ ] **[Medium impact / 1-2 weeks] A single-file desktop launcher.**
  A container still asks for Docker. The audience for this tool overlaps heavily with
  people who will not install a daemon to try something.
  *Do:* a PyInstaller or Briefcase bundle that starts the API, the worker and a browser
  window. Large, but the difference between a demo and a download.

---

## Deliberately not

**Lip sync.** It is what makes the cloud demos go viral and it is the wrong project for it.
It needs face detection, a video generation model and a GPU budget an order of magnitude
past everything else here, and this tool is aimed at narration and documentary, where the
speaker is usually not on screen.

**Real-time or live dubbing.** A different architecture end to end: no review loop, no
resumability, no correcting anything. Everything that makes this project good would have to
be removed.

**A hosted version.** "Nothing leaves your machine" is the strongest claim this project
has. A cloud tier would compete with better-funded services on their terms and give up the
one thing they cannot copy.

**Speech-to-speech translation in one model.** Tempting, and it deletes the segment
boundary that the entire review loop is built on. Worth revisiting only if the review loop
turns out not to matter, which the evidence so far contradicts.

---

## If only three

1. **The glossary UI** — one week, and it fixes the drifting-names problem that makes a
   long dub read as machine output.
2. **A local LLM translator** — the single biggest lift in perceived quality, and the port
   was designed for this exact substitution.
3. **Speaker diarization** — turns a documentary from one flat narrator into something
   people will watch to the end.
