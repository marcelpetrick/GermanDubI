from __future__ import annotations

import json
import sys
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from germandubi.application.ports.providers import (
    AcquisitionRequest,
    SynthesisRequest,
    TranslationRequest,
)
from germandubi.domain.entities.project import SourceKind, SourceRef
from germandubi.domain.entities.segment import Word
from germandubi.domain.errors import (
    CaptionError,
    ProviderUnavailableError,
    SeparationError,
    SourceAcquisitionError,
    SynthesisError,
    TranscriptionError,
    TranslationError,
)
from germandubi.domain.value_objects.timeline import TimeInterval
from germandubi.infrastructure.processes.runner import (
    MAX_STRUCTURED_OUTPUT_BYTES,
    CommandResult,
    ProcessError,
)
from germandubi.infrastructure.providers.argos import ArgosTranslationProvider, _apply_glossary
from germandubi.infrastructure.providers.captions import CaptionTranscriptProvider
from germandubi.infrastructure.providers.demucs import DemucsSeparationProvider
from germandubi.infrastructure.providers.piper import GERMAN_VOICES, PiperTTSProvider, _measure_wav
from germandubi.infrastructure.providers.prosody import TimingProsodyProvider
from germandubi.infrastructure.providers.whisper import WhisperTranscriptionProvider, _to_cue
from germandubi.infrastructure.providers.ytdlp import (
    YtDlpAcquisitionProvider,
    YtDlpProbeProvider,
    _clean_codec,
    _explain,
    _to_source_media,
)


class StubRunner:
    def __init__(self, result: CommandResult | None = None, error: Exception | None = None) -> None:
        self.result = result or CommandResult(("tool",), 0, "", "", 0.01)
        self.error = error
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def is_installed(self, executable: str) -> bool:
        return executable == "installed"

    def run(self, argv: list[str], **kwargs: Any) -> CommandResult:
        self.calls.append((argv, kwargs))
        if self.error is not None:
            raise self.error
        return self.result


def process_error(message: str) -> ProcessError:
    return ProcessError(message)


def test_argos_translation_success_batch_glossary_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ArgosTranslationProvider(auto_install=False)
    translation = SimpleNamespace(translate=lambda text: f"Timing {text}")
    provider._translation = translation

    result = provider.translate(TranslationRequest(" works ", glossary={"timing": "Zeitplan"}))
    assert result.text == "Zeitplan works"
    assert provider.translate_batch([TranslationRequest("one"), TranslationRequest("two")])[1].text
    assert provider.info.id == "argos"
    assert (
        _apply_glossary("Timing timer", {"": "x", "same": "same", "timing": "Takt"}) == "Takt timer"
    )

    with pytest.raises(TranslationError, match="empty"):
        provider.translate(TranslationRequest(" "))
    provider._translation = SimpleNamespace(translate=lambda _text: "")
    with pytest.raises(TranslationError, match="no German"):
        provider.translate(TranslationRequest("text"))
    provider._translation = SimpleNamespace(
        translate=lambda _text: (_ for _ in ()).throw(RuntimeError("bad"))
    )
    with pytest.raises(TranslationError, match="translation failed"):
        provider.translate(TranslationRequest("text"))

    monkeypatch.delitem(sys.modules, "argostranslate", raising=False)
    provider._translation = None
    with pytest.raises(ProviderUnavailableError, match="Argos Translate is unavailable"):
        provider._load()


def test_argos_model_discovery_and_installation() -> None:
    target = SimpleNamespace(code="de")
    expected = object()
    source = SimpleNamespace(
        code="en", get_translation=lambda language: expected if language is target else None
    )
    module = SimpleNamespace(get_installed_languages=lambda: [source, target])
    assert ArgosTranslationProvider._find_installed(module) is expected
    assert (
        ArgosTranslationProvider._find_installed(SimpleNamespace(get_installed_languages=list))
        is None
    )

    broken_source = SimpleNamespace(code="en", get_translation=lambda _target: 1 / 0)
    assert (
        ArgosTranslationProvider._find_installed(
            SimpleNamespace(get_installed_languages=lambda: [broken_source, target])
        )
        is None
    )

    installed: list[Path] = []
    package = SimpleNamespace(
        from_code="en", to_code="de", download=lambda: Path("model.argosmodel")
    )
    module = SimpleNamespace(
        update_package_index=lambda: None,
        get_available_packages=lambda: [package],
        install_from_path=installed.append,
    )
    ArgosTranslationProvider._install_model(module)
    assert installed == [Path("model.argosmodel")]

    with pytest.raises(ProviderUnavailableError, match="does not offer"):
        ArgosTranslationProvider._install_model(
            SimpleNamespace(update_package_index=lambda: None, get_available_packages=list)
        )
    with pytest.raises(ProviderUnavailableError, match="could not download"):
        ArgosTranslationProvider._install_model(
            SimpleNamespace(update_package_index=lambda: 1 / 0, get_available_packages=list)
        )


def write_wav(path: Path, *, frames: int = 2205, rate: int = 22050) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\0\0" * frames)


def test_piper_synthesis_and_wav_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / f"{GERMAN_VOICES[1]}.onnx").touch()
    provider = PiperTTSProvider(voices_dir=voices)
    assert provider.available_voices()[0] == GERMAN_VOICES[1]
    assert provider.info.id == "piper"

    monkeypatch.setattr(provider, "_voice", lambda _name: object())
    monkeypatch.setattr(provider, "_write_wav", lambda _voice, _text, path, _scale: write_wav(path))
    result = provider.synthesize(SynthesisRequest(" Hallo ", "", tmp_path / "speech.wav", 4.0))
    assert result.duration_ms == 100
    assert result.sample_rate == 22050

    with pytest.raises(SynthesisError, match="empty"):
        provider.synthesize(SynthesisRequest(" ", "voice", tmp_path / "x.wav"))
    with pytest.raises(SynthesisError, match="positive"):
        provider.synthesize(SynthesisRequest("text", "voice", tmp_path / "x.wav", 0))
    monkeypatch.setattr(
        provider, "_write_wav", lambda *_args: (_ for _ in ()).throw(OSError("disk"))
    )
    with pytest.raises(SynthesisError, match="synthesis failed"):
        provider.synthesize(SynthesisRequest("text", "voice", tmp_path / "x.wav"))

    class ChunkVoice:
        def synthesize(self, _text: str) -> list[Any]:
            return [
                SimpleNamespace(
                    audio_int16_bytes=b"\0\0" * 10,
                    sample_rate=8000,
                    sample_width=2,
                    sample_channels=1,
                )
            ]

    monkeypatch.setattr(PiperTTSProvider, "_synthesis_config", staticmethod(lambda _scale: None))
    PiperTTSProvider._write_wav(provider, ChunkVoice(), "text", tmp_path / "chunk.wav", 1.0)
    assert _measure_wav(tmp_path / "chunk.wav") == (1, 8000)
    with pytest.raises(SynthesisError, match="could not be read"):
        _measure_wav(tmp_path / "missing.wav")


def test_piper_modern_and_legacy_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = PiperTTSProvider(voices_dir=tmp_path)

    class Modern:
        def __init__(self) -> None:
            self.calls = 0

        def synthesize_wav(self, _text: str, handle: Any, *_args: Any) -> None:
            self.calls += 1
            if self.calls == 1:
                raise TypeError
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(1000)
            handle.writeframes(b"\0\0" * 10)

    monkeypatch.setattr(
        PiperTTSProvider, "_synthesis_config", staticmethod(lambda _scale: object())
    )
    voice = Modern()
    provider._write_wav(voice, "text", tmp_path / "modern.wav", 1.0)
    assert voice.calls == 2


def test_piper_voice_loading_download_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    voices = tmp_path / "voices"
    provider = PiperTTSProvider(voices_dir=voices)
    loaded_voice = object()

    class PiperVoice:
        @staticmethod
        def load(_path: str) -> object:
            return loaded_voice

    piper = ModuleType("piper")
    piper.__path__ = []
    piper.PiperVoice = PiperVoice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper", piper)
    model = voices / "voice.onnx"
    model.parent.mkdir()
    model.touch()
    assert provider.is_available()
    assert provider._voice("voice") is loaded_voice
    assert provider._voice("voice") is loaded_voice

    missing = PiperTTSProvider(voices_dir=voices)
    monkeypatch.setattr(missing, "_download_voice", lambda _name: None)
    with pytest.raises(ProviderUnavailableError, match="could not be downloaded"):
        missing._voice("missing")

    class BrokenVoice:
        @staticmethod
        def load(_path: str) -> object:
            raise RuntimeError("broken model")

    piper.PiperVoice = BrokenVoice  # type: ignore[attr-defined]
    broken = voices / "broken.onnx"
    broken.touch()
    with pytest.raises(ProviderUnavailableError, match="could not be loaded"):
        PiperTTSProvider(voices_dir=voices)._voice("broken")

    download = ModuleType("piper.download_voices")

    def download_voice(name: str, destination: Path) -> None:
        (destination / f"{name}.onnx").touch()

    download.download_voice = download_voice  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper.download_voices", download)
    downloader = PiperTTSProvider(voices_dir=tmp_path / "downloaded")
    downloader._download_voice("new")
    assert (downloader.voices_dir / "new.onnx").exists()
    download.download_voice = lambda *_args: (_ for _ in ()).throw(OSError("offline"))  # type: ignore[attr-defined]
    with pytest.raises(ProviderUnavailableError, match="could not download"):
        downloader._download_voice("bad")


def test_piper_empty_audio_and_synthesis_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = PiperTTSProvider(voices_dir=tmp_path)
    monkeypatch.setattr(provider, "_voice", lambda _name: object())
    monkeypatch.setattr(
        provider, "_write_wav", lambda _voice, _text, path, _scale: write_wav(path, frames=0)
    )
    with pytest.raises(SynthesisError, match="empty audio"):
        provider.synthesize(SynthesisRequest("text", "voice", tmp_path / "empty.wav"))

    config_module = ModuleType("piper.config")
    config_module.SynthesisConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "piper.config", config_module)
    assert PiperTTSProvider._synthesis_config(1.25) == {"length_scale": 1.25}


def test_whisper_mapping_loading_and_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = SimpleNamespace(text="", start=0, end=1)
    assert _to_cue(invalid) is None
    raw_words = [
        SimpleNamespace(word=" hello ", start=0.1, end=0.4, probability=1.5),
        SimpleNamespace(word="", start=0.4, end=0.5, probability=None),
    ]
    raw = SimpleNamespace(text=" Hello ", start=0.0, end=1.0, words=raw_words, avg_logprob=-0.2)
    cue = _to_cue(raw)
    assert (
        cue is not None and cue.words[0].confidence == 1.0 and cue.confidence == pytest.approx(0.8)
    )

    audio = tmp_path / "audio.wav"
    audio.touch()
    model = SimpleNamespace(transcribe=lambda *_args, **_kwargs: ([raw, invalid], object()))
    provider = WhisperTranscriptionProvider(model_size="tiny", download_root=tmp_path)
    provider._model = model
    transcript = provider.transcribe(audio)
    assert transcript.cues[0].text == "Hello"
    assert provider._load() is model
    assert provider.info.model_id == "tiny"

    with pytest.raises(TranscriptionError, match="missing"):
        provider.transcribe(tmp_path / "none.wav")
    provider._model = SimpleNamespace(transcribe=lambda *_a, **_k: ([], None))
    with pytest.raises(TranscriptionError, match="no speech"):
        provider.transcribe(audio)
    provider._model = SimpleNamespace(
        transcribe=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bad"))
    )
    with pytest.raises(TranscriptionError, match="recognition failed"):
        provider.transcribe(audio)

    module = ModuleType("faster_whisper")
    module.WhisperModel = lambda *args, **kwargs: SimpleNamespace(args=args, kwargs=kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    loaded = WhisperTranscriptionProvider(model_size="tiny", download_root=tmp_path)._load()
    assert loaded.args == ("tiny",)


def test_whisper_model_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    module = ModuleType("faster_whisper")
    module.WhisperModel = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("gpu"))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    provider = WhisperTranscriptionProvider()
    assert provider.is_available()
    with pytest.raises(ProviderUnavailableError, match="could not load"):
        provider._load()


def test_demucs_success_and_failures(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.touch()

    class DemucsRunner(StubRunner):
        def run(self, argv: list[str], **kwargs: Any) -> CommandResult:
            result = super().run(argv, **kwargs)
            work = Path(argv[argv.index("--out") + 1]) / "model" / "track"
            work.mkdir(parents=True)
            (work / "no_vocals.wav").write_bytes(b"background")
            (work / "vocals.wav").write_bytes(b"voice")
            return result

    provider = DemucsSeparationProvider(DemucsRunner(), model="model")  # type: ignore[arg-type]
    result = provider.separate(audio, tmp_path / "stems")
    assert result.background_path.read_bytes() == b"background"
    assert result.voice_path is not None and result.voice_path.read_bytes() == b"voice"
    assert provider.info.model_id == "model"

    with pytest.raises(SeparationError, match="missing"):
        provider.separate(tmp_path / "none.wav", tmp_path / "x")
    failed = DemucsSeparationProvider(StubRunner(error=process_error("boom")))  # type: ignore[arg-type]
    with pytest.raises(SeparationError, match="failed"):
        failed.separate(audio, tmp_path / "failed")
    no_stems = DemucsSeparationProvider(StubRunner())  # type: ignore[arg-type]
    with pytest.raises(SeparationError, match="no background"):
        no_stems.separate(audio, tmp_path / "empty")


def test_caption_provider_formats_and_errors(tmp_path: Path) -> None:
    vtt = tmp_path / "captions.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello world\n")
    manual = CaptionTranscriptProvider(vtt, automatic=False)
    assert manual.is_available()
    assert manual.info.id == "captions_manual"
    assert manual.transcribe(tmp_path / "ignored").cues[0].text == "Hello world"

    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    automatic = CaptionTranscriptProvider(srt, automatic=True)
    assert automatic.info.notes and automatic.transcribe(tmp_path / "ignored").cues

    with pytest.raises(CaptionError, match="missing or empty"):
        CaptionTranscriptProvider(tmp_path / "none.vtt", automatic=False).transcribe(tmp_path / "x")
    unknown = tmp_path / "captions.txt"
    unknown.write_text("content")
    with pytest.raises(CaptionError, match="unsupported"):
        CaptionTranscriptProvider(unknown, automatic=False).transcribe(tmp_path / "x")


def youtube() -> SourceRef:
    return SourceRef(
        SourceKind.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", "abcdefghijk"
    )


def test_ytdlp_probe_mapping_and_errors() -> None:
    payload = {
        "title": "Video",
        "duration": 1.25,
        "channel": "Channel",
        "thumbnail": "https://example.test/image.jpg",
        "vcodec": "avc1.123",
        "acodec": "none",
        "width": 1920,
        "height": 1080,
        "subtitles": {"en-US": [{"ext": "srt"}, {"ext": "vtt", "name": "English"}]},
        "automatic_captions": {"de": [{"ext": "vtt"}]},
    }
    runner = StubRunner(CommandResult(("yt-dlp",), 0, json.dumps(payload), "", 0.1))
    provider = YtDlpProbeProvider(runner, executable="installed")  # type: ignore[arg-type]
    media = provider.probe(youtube())
    assert media.duration_ms == 1250 and media.captions[0].name == "English"
    assert media.video_codec == "avc1" and media.audio_codec is None
    assert provider.is_available() and provider.info.kind == "network"

    with pytest.raises(SourceAcquisitionError, match="cannot inspect"):
        provider.probe(SourceRef(SourceKind.LOCAL_FILE, "/media/file"))
    bad_json = YtDlpProbeProvider(StubRunner(CommandResult(("x",), 0, "not json", "", 0.1)))  # type: ignore[arg-type]
    with pytest.raises(SourceAcquisitionError, match="metadata"):
        bad_json.probe(youtube())
    failed = YtDlpProbeProvider(StubRunner(error=process_error("private video")))  # type: ignore[arg-type]
    with pytest.raises(SourceAcquisitionError, match="private"):
        failed.probe(youtube())

    # A real 40-minute video's metadata exceeded the old 256 KB capture limit, so the
    # probe received half a JSON document and blamed the source site for a local bug.
    assert runner.calls[0][1]["max_output_bytes"] >= MAX_STRUCTURED_OUTPUT_BYTES
    truncated = YtDlpProbeProvider(
        StubRunner(  # type: ignore[arg-type]
            CommandResult(("yt-dlp",), 0, json.dumps(payload)[:20], "", 0.1, stdout_truncated=True)
        )
    )
    with pytest.raises(SourceAcquisitionError, match="not in the source"):
        truncated.probe(youtube())

    with pytest.raises(SourceAcquisitionError, match="no duration"):
        _to_source_media({"title": "Live"})
    assert _clean_codec("") is None and _clean_codec("vp09.00") == "vp09"
    assert _explain("ERROR: unknown\nlast line") == "last line"
    assert _explain("") == "the source could not be read"


def test_ytdlp_acquisition_local_remote_and_discovery(tmp_path: Path) -> None:
    provider = YtDlpAcquisitionProvider(StubRunner(), executable="installed")  # type: ignore[arg-type]
    source = tmp_path / "input.mp4"
    source.write_bytes(b"media")
    local = provider.acquire(
        AcquisitionRequest(SourceRef(SourceKind.LOCAL_FILE, str(source)), tmp_path / "local")
    )
    assert local.video_path.read_bytes() == b"media"
    assert provider.is_available() and provider.info.id == "yt_dlp"

    with pytest.raises(SourceAcquisitionError, match="does not exist"):
        provider.acquire(
            AcquisitionRequest(
                SourceRef(SourceKind.LOCAL_FILE, str(tmp_path / "none")), tmp_path / "x"
            )
        )

    destination = tmp_path / "remote"
    destination.mkdir()
    (destination / "source.webm").write_bytes(b"small")
    (destination / "source.mkv").write_bytes(b"larger media")
    (destination / "source.en.vtt").write_text("manual")
    (destination / "source.en-orig.vtt").write_text("auto")
    acquired = provider.acquire(AcquisitionRequest(youtube(), destination, want_captions=True))
    assert acquired.video_path.name == "source.mkv"
    assert set(acquired.caption_paths) == {False, True}

    with pytest.raises(SourceAcquisitionError, match="no media"):
        YtDlpAcquisitionProvider._find_media(tmp_path / "nothing")
    failed = YtDlpAcquisitionProvider(StubRunner(error=process_error("video unavailable")))  # type: ignore[arg-type]
    with pytest.raises(SourceAcquisitionError, match="unavailable"):
        failed.acquire(AcquisitionRequest(youtube(), tmp_path / "failed"))


def test_timing_prosody_loudness_and_fallbacks(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.touch()
    interval = TimeInterval(0, 2000)
    words = (Word(200, 700, "one"), Word(900, 1400, "two"))
    runner = StubRunner(CommandResult(("ffmpeg",), 0, "", "mean_volume: -30.0 dB", 0.1))
    provider = TimingProsodyProvider(runner)  # type: ignore[arg-type]
    profile = provider.analyse(audio, interval, words=words)
    assert profile.speech_rate_wps == 2.0
    assert profile.pause_before_ms == 200 and profile.pause_after_ms == 600
    assert profile.energy_rms == 0.5 and provider.info.id == "timing_prosody"

    assert TimingProsodyProvider().analyse(audio, interval).energy_rms is None
    no_match = TimingProsodyProvider(StubRunner())  # type: ignore[arg-type]
    assert no_match.analyse(audio, interval).energy_rms is None
    failed = TimingProsodyProvider(StubRunner(error=process_error("bad")))  # type: ignore[arg-type]
    assert failed.analyse(audio, interval).energy_rms is None
