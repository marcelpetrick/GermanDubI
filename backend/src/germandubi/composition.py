"""Composition root.

The one place that knows about concrete implementations and wires them to ports. The API,
the worker and the CLI all build their dependencies here, so there is a single answer to
"what is actually running", and so the layering rule - nothing imports infrastructure except
the composition root - has somewhere to be true.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from germandubi.application.services.pipeline import PipelineService
from germandubi.application.services.projects import ProjectService
from germandubi.application.services.segments import SegmentService
from germandubi.application.services.unit_of_work import UnitOfWorkFactory
from germandubi.config import Settings, get_settings
from germandubi.infrastructure.artifacts.store import ArtifactStore
from germandubi.infrastructure.db.session import Database, create_database
from germandubi.infrastructure.processes.runner import ProcessRunner
from germandubi.infrastructure.providers.registry import ProviderRegistry
from germandubi.worker.runner import Worker

__all__ = ["Application", "build_application", "configure_logging"]

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    """Set up application logging.

    Args:
        settings: Application settings naming the level and format.
    """
    logging.basicConfig(
        level=settings.log_level,
        format=(
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
            '"message":"%(message)s"}'
            if settings.log_format == "json"
            else "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
        ),
        datefmt="%H:%M:%S",
        force=True,
    )
    # These libraries log every request or tokenization at INFO, drowning our own output.
    for noisy in ("httpx", "sqlalchemy.engine", "argostranslate", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@dataclass(frozen=True, slots=True)
class Application:
    """Everything the process needs, wired together.

    Attributes:
        settings: Application settings.
        database: The database.
        store: The filesystem artifact store.
        registry: Provider selection.
        unit_of_work: Transaction factory.
        projects: Project use cases.
        pipeline: Run use cases.
        segments: Segment review use cases.
    """

    settings: Settings
    database: Database
    store: ArtifactStore
    registry: ProviderRegistry
    unit_of_work: UnitOfWorkFactory
    projects: ProjectService
    pipeline: PipelineService
    segments: SegmentService

    def worker(self) -> Worker:
        """Build a processing worker sharing this application's wiring.

        Returns:
            A worker ready to claim jobs.
        """
        return Worker(
            unit_of_work=self.unit_of_work, registry=self.registry, settings=self.settings
        )

    def dispose(self) -> None:
        """Release database connections."""
        self.database.dispose()


def build_application(
    settings: Settings | None = None,
    *,
    create_schema: bool = True,
    fixture: Path | None = None,
) -> Application:
    """Wire the application together.

    Args:
        settings: Settings to use; read from the environment when omitted.
        create_schema: Whether to create missing tables. Convenient for first start and for
            tests; production schema changes still go through Alembic.
        fixture: A local media file for the fake acquisition provider, used by tests. The
            configured fake fixture is used when this explicit override is omitted.

    Returns:
        The wired application.
    """
    resolved = settings or get_settings()
    resolved.ensure_directories()

    database = create_database(resolved.resolved_database_url)
    if create_schema:
        database.create_all()

    store = ArtifactStore(resolved.projects_dir)
    unit_of_work = UnitOfWorkFactory(database, store)
    registry = ProviderRegistry(
        resolved,
        runner=ProcessRunner(default_timeout_s=resolved.process_timeout_s),
        fixture=fixture if fixture is not None else resolved.fake_media_fixture,
    )

    return Application(
        settings=resolved,
        database=database,
        store=store,
        registry=registry,
        unit_of_work=unit_of_work,
        projects=ProjectService(unit_of_work),
        pipeline=PipelineService(unit_of_work),
        segments=SegmentService(unit_of_work),
    )
