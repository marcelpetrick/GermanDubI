"""Typed application configuration.

Settings come from, in increasing precedence: built-in defaults, a ``.env`` file, and
environment variables prefixed ``GERMANDUBI_``. Provider credentials are never stored in
project files; they come from the environment.

User project data defaults to the XDG data directory rather than the Git checkout, so that
a clone stays clean and media is never accidentally committed (docs/project/questions.md Q-D5).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings", "reset_settings_cache"]


def _default_data_dir() -> Path:
    """Return the default root for project data, honouring ``XDG_DATA_HOME``."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "germandubi"


def _default_frontend_dist() -> Path | None:
    """Return the repository frontend build when running from a source checkout."""
    candidate = Path.cwd() / "frontend" / "dist"
    return candidate.resolve() if candidate.is_dir() else None


class Settings(BaseSettings):
    """Runtime configuration for the API process, the worker and the CLI."""

    model_config = SettingsConfigDict(
        env_prefix="GERMANDUBI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- storage ---
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        description="Root directory for project workspaces and the database.",
    )
    database_url: str | None = Field(
        default=None,
        description="SQLAlchemy URL. Defaults to a SQLite file inside data_dir.",
    )

    # --- server ---
    host: str = Field(default="127.0.0.1", description="API bind address; loopback by default.")
    port: int = Field(default=8756, ge=1, le=65535, description="API port.")
    cors_origins: tuple[str, ...] = Field(
        default=("http://localhost:5173", "http://127.0.0.1:5173"),
        description="Origins allowed to call the API, for the Vite dev server.",
    )
    frontend_dist: Path | None = Field(
        default_factory=_default_frontend_dist,
        description="Compiled browser bundle served by the API, when present.",
    )

    # --- worker ---
    worker_poll_interval_s: float = Field(default=0.5, gt=0, le=30)
    job_lease_seconds: int = Field(
        default=900,
        gt=0,
        description="How long a claimed job stays owned before another worker may reclaim it.",
    )
    process_timeout_s: int = Field(
        default=3600, gt=0, description="Ceiling for any single external process."
    )
    sse_stream_seconds: float = Field(
        default=600.0,
        gt=0,
        description=(
            "How long one progress stream stays open before closing. The browser "
            "reconnects automatically and replays what it missed, so bounding the "
            "generator's lifetime costs nothing and stops connections accumulating."
        ),
    )

    # --- providers ---
    transcription_provider: str = Field(default="auto")
    translation_provider: str = Field(default="auto")
    tts_provider: str = Field(default="auto")
    separation_provider: str = Field(default="auto")
    fake_media_fixture: Path | None = Field(
        default=None,
        description="Local media copied by fake acquisition in deterministic E2E runs.",
    )
    tts_voice: str = Field(
        default="de_DE-thorsten-high",
        description="German voice used by a project that does not choose one.",
    )
    device: Literal["auto", "cpu", "cuda"] = Field(
        default="auto",
        description=(
            "Compute device for the model providers. 'auto' uses a CUDA GPU when one is "
            "usable and falls back to the CPU, which is the only device the pipeline "
            "requires."
        ),
    )
    allow_network_providers: bool = Field(
        default=False,
        description="Whether a provider that sends data off the machine may be selected.",
    )

    # --- pipeline tuning (docs/project/questions.md Q-C6) ---
    max_time_stretch: float = Field(
        default=0.08,
        gt=0,
        le=0.5,
        description="Largest acoustic time-stretch applied to fit German speech, as a fraction.",
    )
    max_speaking_rate_adjustment: float = Field(
        default=0.15, gt=0, le=0.5, description="Largest TTS speaking-rate change, as a fraction."
    )
    duration_warning_threshold: float = Field(
        default=0.15,
        gt=0,
        description="Relative overrun above which a segment is flagged rather than forced.",
    )

    # --- tools ---
    ffmpeg_path: str = Field(default="ffmpeg")
    ffprobe_path: str = Field(default="ffprobe")
    yt_dlp_path: str = Field(default="yt-dlp")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["text", "json"] = Field(default="text")
    log_file: Path | None = Field(
        default=None,
        description=(
            "Where the server log is written. Defaults to a rotating file inside data_dir. "
            "Set GERMANDUBI_LOG_FILE to 'none' to log only to the console."
        ),
    )
    log_max_bytes: int = Field(
        default=5_000_000,
        gt=0,
        description="Size at which the log file rotates.",
    )
    log_backup_count: int = Field(
        default=3, ge=0, description="How many rotated log files to keep."
    )

    @field_validator("data_dir")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        """Expand ``~`` and resolve the data directory to an absolute path."""
        return value.expanduser().resolve()

    @field_validator("frontend_dist", "fake_media_fixture")
    @classmethod
    def _expand_optional(cls, value: Path | None) -> Path | None:
        """Resolve an optional configured path."""
        return value.expanduser().resolve() if value is not None else None

    @field_validator("log_file")
    @classmethod
    def _expand_log_file(cls, value: Path | None) -> Path | None:
        """Resolve the log file, leaving the ``none`` sentinel alone for the property."""
        if value is None or value.name.lower() in {"none", "off"}:
            return value
        return value.expanduser().resolve()

    @property
    def projects_dir(self) -> Path:
        """Return the directory holding one workspace per project."""
        return self.data_dir / "projects"

    def resolved_device(self) -> str:
        """Return the device the model providers should actually use.

        Resolved once, here, rather than by each provider: a run where recognition used the
        GPU and separation quietly used the CPU is the confusing case, and 'auto' has to
        mean the same thing to everyone. Detection is deliberately tolerant -- a machine
        with a driver problem should dub slowly, not fail.
        """
        if self.device != "auto":
            return self.device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            # Any import or driver failure means no usable GPU, never a failed run.
            return "cpu"

    @property
    def models_dir(self) -> Path:
        """Return the directory holding downloaded model files."""
        return self.data_dir / "models"

    @property
    def logs_dir(self) -> Path:
        """Return the directory holding the server log."""
        return self.data_dir / "logs"

    @property
    def resolved_log_file(self) -> Path | None:
        """Return the file the server log is written to, or ``None`` for console only.

        A console-only log is fine while a terminal is watching it and useless afterwards.
        The error a user reports is almost always one they have already scrolled past, so
        the log has to outlive the terminal and live somewhere nameable -- the message in
        the browser names this path.
        """
        if self.log_file is not None:
            return None if self.log_file.name.lower() in {"none", "off"} else self.log_file
        return self.logs_dir / "germandubi.log"

    @property
    def resolved_database_url(self) -> str:
        """Return the SQLAlchemy URL, defaulting to SQLite inside the data directory."""
        if self.database_url:
            return self.database_url
        return f"sqlite+pysqlite:///{self.data_dir / 'germandubi.db'}"

    def ensure_directories(self) -> None:
        """Create the data directories if they do not exist."""
        for directory in (self.data_dir, self.projects_dir, self.models_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read once.

    Returns:
        The cached :class:`Settings`.
    """
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache so tests can rebind the environment."""
    get_settings.cache_clear()
