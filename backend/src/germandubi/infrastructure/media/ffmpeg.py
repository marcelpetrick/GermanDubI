"""FFmpeg and FFprobe adapter implementing :class:`MediaToolkit`.

Everything here builds argument arrays and hands them to the process runner. No command is
ever assembled as a string, because several arguments - file names derived from video
titles, filter graphs containing user-influenced numbers - would otherwise be a shell
injection surface.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Final

from germandubi.application.ports.providers import AudioInfo, MixRequest
from germandubi.domain.errors import ExportError, MediaProcessingError, MixError
from germandubi.domain.value_objects.timeline import TimeInterval, ms_to_seconds, seconds_to_ms
from germandubi.infrastructure.processes.runner import (
    MAX_STRUCTURED_OUTPUT_BYTES,
    ProcessError,
    ProcessRunner,
)

__all__ = ["ASR_SAMPLE_RATE", "MASTER_SAMPLE_RATE", "FFmpegToolkit"]

logger = logging.getLogger(__name__)

#: Speech recognition models are trained on 16 kHz mono; anything else is resampled anyway.
ASR_SAMPLE_RATE: Final = 16_000
#: The master audio keeps 48 kHz stereo so mixing and export do not lose quality.
MASTER_SAMPLE_RATE: Final = 48_000
#: Broadcast loudness target, so the German dub is as loud as the original.
LOUDNESS_TARGET_LUFS: Final = -16.0
#: How many clips one assembly pass may place. Above this the work is split into batches
#: and the batch results summed, which is bit-identical and markedly faster.
_PLACEMENTS_PER_PASS: Final = 50
#: How many speech intervals one ducking ``volume`` filter may name. Chosen well below the
#: size at which FFmpeg fails to evaluate the expression, since the cost of another filter
#: in the chain is negligible next to the cost of a mix that cannot run at all.
_DUCK_INTERVALS_PER_FILTER: Final = 40


class FFmpegToolkit:
    """Media operations backed by the FFmpeg command-line tools.

    Attributes:
        runner: The process runner used for every invocation.
        ffmpeg: Path or name of the ``ffmpeg`` executable.
        ffprobe: Path or name of the ``ffprobe`` executable.
    """

    def __init__(
        self,
        runner: ProcessRunner,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
    ) -> None:
        """Initialise the toolkit.

        Args:
            runner: The process runner to use.
            ffmpeg: Name or path of the ``ffmpeg`` executable.
            ffprobe: Name or path of the ``ffprobe`` executable.
        """
        self.runner = runner
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def is_available(self) -> bool:
        """Return whether both FFmpeg tools are installed."""
        return self.runner.is_installed(self.ffmpeg) and self.runner.is_installed(self.ffprobe)

    # --- inspection ---------------------------------------------------------------------

    def probe(self, path: Path) -> AudioInfo:
        """Inspect a media file with ``ffprobe``.

        Args:
            path: The file to inspect.

        Returns:
            Duration and stream information.

        Raises:
            MediaProcessingError: If the file is missing or cannot be inspected.
        """
        if not path.exists():
            msg = f"cannot inspect a file that does not exist: {path.name}"
            raise MediaProcessingError(msg, path=str(path))
        try:
            result = self.runner.run(
                [
                    self.ffprobe,
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(path),
                ],
                timeout_s=120,
                max_output_bytes=MAX_STRUCTURED_OUTPUT_BYTES,
            )
        except ProcessError as exc:
            msg = f"could not inspect {path.name}: {exc.message}"
            raise MediaProcessingError(msg, path=str(path)) from exc

        if result.stdout_truncated:
            msg = f"ffprobe returned more metadata than can be held for {path.name}"
            raise MediaProcessingError(msg, path=str(path))
        try:
            payload: dict[str, Any] = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            msg = f"ffprobe returned output that is not JSON for {path.name}"
            raise MediaProcessingError(msg, path=str(path)) from exc

        return self._to_audio_info(payload, path)

    @staticmethod
    def _to_audio_info(payload: dict[str, Any], path: Path) -> AudioInfo:
        """Map an ``ffprobe`` JSON document onto the application's own type.

        Provider output is mapped immediately rather than persisted as-is, so an FFmpeg
        schema change cannot ripple through the domain.
        """
        streams: list[dict[str, Any]] = payload.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

        duration_raw = payload.get("format", {}).get("duration")
        if duration_raw is None and audio is not None:
            duration_raw = audio.get("duration")
        try:
            duration_ms = seconds_to_ms(float(duration_raw)) if duration_raw else 0
        except (TypeError, ValueError):
            duration_ms = 0
        if duration_ms <= 0:
            msg = f"{path.name} reports no usable duration; it may be truncated or not media"
            raise MediaProcessingError(msg, path=str(path))

        return AudioInfo(
            duration_ms=duration_ms,
            sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
            channels=int(audio["channels"]) if audio and audio.get("channels") else None,
            has_video=video is not None,
            video_codec=video.get("codec_name") if video else None,
            audio_codec=audio.get("codec_name") if audio else None,
            width=int(video["width"]) if video and video.get("width") else None,
            height=int(video["height"]) if video and video.get("height") else None,
        )

    # --- extraction ---------------------------------------------------------------------

    def extract_audio(
        self,
        source: Path,
        destination: Path,
        *,
        sample_rate: int = MASTER_SAMPLE_RATE,
        mono: bool = False,
        normalize_loudness: bool = False,
    ) -> Path:
        """Extract an audio track as WAV.

        Uncompressed WAV is used for every intermediate audio artifact. Repeatedly decoding
        and re-encoding a lossy format between pipeline stages accumulates artefacts, and
        the intermediates are deleted with the project anyway.

        Args:
            source: The media file.
            destination: Where to write the audio.
            sample_rate: Target sample rate.
            mono: Whether to downmix to one channel.
            normalize_loudness: Whether to apply EBU R128 loudness normalization.

        Returns:
            The written file.

        Raises:
            MediaProcessingError: If extraction fails or produces nothing.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        argv = [self.ffmpeg, "-y", "-nostdin", "-i", str(source), "-vn"]
        if normalize_loudness:
            argv += ["-af", f"loudnorm=I={LOUDNESS_TARGET_LUFS}:TP=-1.5:LRA=11"]
        argv += [
            "-ac",
            "1" if mono else "2",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
        self._run_media(argv, failure=f"could not extract audio from {source.name}")
        return self._require_output(destination, f"audio extraction from {source.name}")

    # --- narration assembly -------------------------------------------------------------

    def concatenate_speech(
        self,
        placements: list[tuple[TimeInterval, Path]],
        destination: Path,
        *,
        total_ms: int,
        sample_rate: int = MASTER_SAMPLE_RATE,
    ) -> Path:
        """Place per-segment speech clips onto one silent narration track.

        Each clip is delayed to its own timeline position rather than concatenated
        end-to-end. Concatenation would make every clip's position depend on the exact
        length of all the clips before it, so a single segment regenerated at a slightly
        different length would desynchronize the entire rest of the video.

        Args:
            placements: Timeline position and audio file for each segment.
            destination: Where to write the narration track.
            total_ms: Total length of the track.
            sample_rate: Output sample rate.

        Returns:
            The written file.

        Raises:
            MixError: If assembly fails.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not placements:
            return self.silence(destination, duration_ms=total_ms, sample_rate=sample_rate)

        if len(placements) <= _PLACEMENTS_PER_PASS:
            self._place(placements, destination, total_ms=total_ms, sample_rate=sample_rate)
            return self._require_output(destination, "narration assembly")

        # One `amix` over every segment makes FFmpeg hold a decoder and a full-length
        # buffer per input, and the cost grows faster than the segment count: a real
        # 400-segment dub took 94 s in one pass and 34 s in batches, for bit-identical
        # output. Mixing in batches and then mixing the batches keeps each graph small.
        staging = destination.parent / "_assemble"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            partials: list[Path] = []
            for index in range(0, len(placements), _PLACEMENTS_PER_PASS):
                batch = placements[index : index + _PLACEMENTS_PER_PASS]
                partial = staging / f"part_{index:05d}.wav"
                self._place(batch, partial, total_ms=total_ms, sample_rate=sample_rate)
                partials.append(self._require_output(partial, "narration assembly"))
            self._combine(partials, destination, sample_rate=sample_rate)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return self._require_output(destination, "narration assembly")

    def _place(
        self,
        placements: list[tuple[TimeInterval, Path]],
        destination: Path,
        *,
        total_ms: int,
        sample_rate: int,
    ) -> None:
        """Mix one batch of clips onto a full-length silent track at their own positions."""
        argv: list[str] = [self.ffmpeg, "-y", "-nostdin"]
        for _, clip in placements:
            argv += ["-i", str(clip)]

        filters: list[str] = []
        labels: list[str] = []
        for index, (interval, _) in enumerate(placements):
            label = f"d{index}"
            filters.append(
                f"[{index}:a]aresample={sample_rate},"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"adelay={interval.start_ms}:all=1[{label}]"
            )
            labels.append(f"[{label}]")
        filters.append(
            f"{''.join(labels)}amix=inputs={len(placements)}:normalize=0:dropout_transition=0"
            f"[mixed]"
        )
        # apad + atrim pins the track to exactly the media duration, so the narration and
        # the video stay the same length whatever the last segment does.
        filters.append(f"[mixed]apad,atrim=0:{ms_to_seconds(total_ms):.3f},asetpts=N/SR/TB[out]")

        argv += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
        try:
            self.runner.run(argv, timeout_s=self.runner.default_timeout_s)
        except ProcessError as exc:
            msg = f"could not assemble the German narration track: {exc.message}"
            raise MixError(msg) from exc

    def _combine(self, partials: list[Path], destination: Path, *, sample_rate: int) -> None:
        """Sum already-positioned, equal-length tracks into one.

        Every partial is the full length with silence where it has no speech, so summing
        them reproduces exactly what one pass over all the clips would have produced.
        """
        argv: list[str] = [self.ffmpeg, "-y", "-nostdin"]
        for partial in partials:
            argv += ["-i", str(partial)]
        inputs = "".join(f"[{index}:a]" for index in range(len(partials)))
        argv += [
            "-filter_complex",
            f"{inputs}amix=inputs={len(partials)}:normalize=0:dropout_transition=0[out]",
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
        try:
            self.runner.run(argv, timeout_s=self.runner.default_timeout_s)
        except ProcessError as exc:
            msg = f"could not combine the German narration batches: {exc.message}"
            raise MixError(msg) from exc

    def silence(
        self, destination: Path, *, duration_ms: int, sample_rate: int = MASTER_SAMPLE_RATE
    ) -> Path:
        """Write a silent stereo WAV of a given length.

        Args:
            destination: Where to write the file.
            duration_ms: Length of the silence.
            sample_rate: Output sample rate.

        Returns:
            The written file.

        Raises:
            MediaProcessingError: If the file cannot be written.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run_media(
            [
                self.ffmpeg,
                "-y",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={sample_rate}:cl=stereo",
                "-t",
                f"{ms_to_seconds(max(duration_ms, 1)):.3f}",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            failure="could not generate silence",
        )
        return self._require_output(destination, "silence generation")

    # --- mixing -------------------------------------------------------------------------

    def mix(self, request: MixRequest) -> Path:
        """Combine the German narration with background audio.

        Two strategies, chosen by what is available. When a separated background stem
        exists, the narration is mixed straight onto it. Otherwise the original audio is
        ducked - attenuated only while German speech plays - which needs no ML model and
        always works, at the cost of leaving the English voice faintly audible
        (docs/project/questions.md Q-A3).

        Args:
            request: What to mix and how.

        Returns:
            The written mixed audio file.

        Raises:
            MixError: If mixing fails.
        """
        request.destination.parent.mkdir(parents=True, exist_ok=True)
        bed = request.background_path or request.original_path
        if bed is None:
            shutil.copyfile(request.narration_path, request.destination)
            return request.destination

        argv = [
            self.ffmpeg,
            "-y",
            "-nostdin",
            "-i",
            str(bed),
            "-i",
            str(request.narration_path),
        ]
        if request.background_path is not None:
            graph = (
                "[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo[bed];"
                "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[voice];"
                "[bed][voice]amix=inputs=2:normalize=0:dropout_transition=0[out]"
            )
        else:
            graph = (
                f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo"
                f"{self._ducking_filter(request.speech_intervals, request.duck_db)}[bed];"
                "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[voice];"
                "[bed][voice]amix=inputs=2:normalize=0:dropout_transition=0[out]"
            )
        argv += [
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-ac",
            "2",
            "-ar",
            str(MASTER_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(request.destination),
        ]
        try:
            self.runner.run(argv)
        except ProcessError as exc:
            msg = f"could not mix the German audio: {exc.message}"
            raise MixError(msg) from exc
        return self._require_output(request.destination, "mixing")

    @staticmethod
    def _ducking_filter(intervals: tuple[TimeInterval, ...], duck_db: float) -> str:
        """Build volume filters that attenuate the original audio under German speech.

        Returns an empty string when there is nothing to duck.

        Adjacent intervals are merged first, but merging alone is not enough. A
        40-minute narration yields hundreds of separate speech runs even after merging,
        and one ``enable`` expression naming all of them is tens of kilobytes long --
        which FFmpeg fails to evaluate outright:

            Error when evaluating the expression '...' for enable
            Error initializing filters ... Cannot allocate memory

        So the intervals are spread over several chained ``volume`` filters instead. The
        chaining is safe precisely because the merged intervals are disjoint: at any
        instant at most one filter has its ``enable`` satisfied, and the rest pass the
        signal through at unity gain, so the attenuation never compounds.
        """
        if not intervals:
            return ""
        merged: list[TimeInterval] = []
        for interval in sorted(intervals, key=lambda i: i.start_ms):
            if merged and interval.start_ms <= merged[-1].end_ms + 250:
                merged[-1] = merged[-1].merged_with(interval)
            else:
                merged.append(interval)

        gain = 10 ** (duck_db / 20)
        stages = []
        for index in range(0, len(merged), _DUCK_INTERVALS_PER_FILTER):
            batch = merged[index : index + _DUCK_INTERVALS_PER_FILTER]
            conditions = "+".join(
                f"between(t,{ms_to_seconds(i.start_ms):.3f},{ms_to_seconds(i.end_ms):.3f})"
                for i in batch
            )
            stages.append(f"volume=enable='gt({conditions}\\,0)':volume={gain:.4f}:eval=frame")
        return "," + ",".join(stages)

    def time_stretch(self, source: Path, destination: Path, *, factor: float) -> Path:
        """Change a clip's duration without changing its pitch.

        Args:
            source: The clip to stretch.
            destination: Where to write the result.
            factor: Speed factor; above ``1.0`` shortens the clip. FFmpeg's ``atempo``
                accepts 0.5-2.0 per instance, so larger factors are chained.

        Returns:
            The written file.

        Raises:
            MediaProcessingError: If the factor is not usable or the operation fails.
        """
        if factor <= 0:
            msg = f"time-stretch factor must be positive, got {factor}"
            raise MediaProcessingError(msg, factor=factor)
        destination.parent.mkdir(parents=True, exist_ok=True)

        stages: list[float] = []
        remaining = factor
        while remaining > 2.0:
            stages.append(2.0)
            remaining /= 2.0
        while remaining < 0.5:
            stages.append(0.5)
            remaining /= 0.5
        stages.append(remaining)

        self._run_media(
            [
                self.ffmpeg,
                "-y",
                "-nostdin",
                "-i",
                str(source),
                "-filter:a",
                ",".join(f"atempo={s:.6f}" for s in stages),
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            failure=f"could not time-stretch {source.name}",
        )
        return self._require_output(destination, "time stretching")

    # --- export -------------------------------------------------------------------------

    def mux(
        self,
        *,
        video_source: Path,
        german_audio: Path,
        destination: Path,
        original_audio: Path | None = None,
        subtitles: dict[str, Path] | None = None,
    ) -> Path:
        """Mux the German dub into its final container.

        The video stream is copied rather than re-encoded: re-encoding a 20-minute video
        would dominate the whole pipeline's runtime and would lose quality for nothing.

        Args:
            video_source: The file holding the original video stream.
            german_audio: The mixed German audio, made the default track.
            destination: Where to write the output.
            original_audio: The original audio, kept as a second track.
            subtitles: Subtitle files keyed by language code.

        Returns:
            The written file.

        Raises:
            ExportError: If muxing fails.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        is_mp4 = destination.suffix.lower() == ".mp4"
        subtitle_tracks = dict(subtitles or {})

        argv = [self.ffmpeg, "-y", "-nostdin", "-i", str(video_source), "-i", str(german_audio)]
        inputs = 2
        original_index: int | None = None
        if original_audio is not None:
            argv += ["-i", str(original_audio)]
            original_index = inputs
            inputs += 1

        subtitle_indices: dict[str, int] = {}
        for language, path in subtitle_tracks.items():
            argv += ["-i", str(path)]
            subtitle_indices[language] = inputs
            inputs += 1

        argv += ["-map", "0:v:0", "-map", "1:a:0"]
        if original_index is not None:
            argv += ["-map", f"{original_index}:a:0"]
        for index in subtitle_indices.values():
            argv += ["-map", f"{index}:s:0"]

        # The narration is the point of the file; 256 kbit/s keeps the encoder well clear
        # of the speech it is carrying. Piper's 22.05 kHz output is the real ceiling.
        argv += ["-c:v", "copy", "-c:a", "aac", "-b:a", "256k"]
        # MP4 only carries mov_text subtitles; Matroska takes SRT directly.
        argv += ["-c:s", "mov_text" if is_mp4 else "srt"]

        argv += ["-metadata:s:a:0", "language=deu", "-metadata:s:a:0", "title=German dub"]
        argv += ["-disposition:a:0", "default"]
        if original_index is not None:
            argv += [
                "-metadata:s:a:1",
                "language=eng",
                "-metadata:s:a:1",
                "title=Original English",
                "-disposition:a:1",
                "0",
            ]
        for position, language in enumerate(subtitle_indices):
            code = {"de": "deu", "en": "eng"}.get(language, language)
            argv += [f"-metadata:s:s:{position}", f"language={code}"]

        argv.append(str(destination))
        try:
            self.runner.run(argv)
        except ProcessError as exc:
            msg = f"could not write the export: {exc.message}"
            raise ExportError(msg, destination=destination.name) from exc
        return self._require_output(destination, "export")

    # --- helpers ------------------------------------------------------------------------

    def _run_media(self, argv: list[str], *, failure: str) -> None:
        """Run an FFmpeg command, wrapping failures in a domain error."""
        try:
            self.runner.run(argv)
        except ProcessError as exc:
            msg = f"{failure}: {exc.message}"
            raise MediaProcessingError(msg) from exc

    @staticmethod
    def _require_output(path: Path, operation: str) -> Path:
        """Verify that an operation actually produced a non-empty file.

        FFmpeg can exit zero having written nothing, for instance when a filter graph
        selects no samples. Checking here turns that into an immediate, attributable error
        rather than a confusing failure two stages later.
        """
        if not path.exists() or path.stat().st_size == 0:
            msg = f"{operation} reported success but produced no output"
            raise MediaProcessingError(msg, path=str(path))
        return path
