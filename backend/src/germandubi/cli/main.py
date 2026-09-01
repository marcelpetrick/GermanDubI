"""The ``germandubi`` command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from germandubi.application.services.pipeline import RunProgress
from germandubi.composition import build_application, configure_logging
from germandubi.config import Settings, get_settings
from germandubi.domain.entities.artifact import ArtifactKind
from germandubi.domain.entities.project import QualityProfile
from germandubi.domain.errors import GermanDubIError, ResourceError
from germandubi.domain.value_objects.identifiers import ProjectId, Ulid
from germandubi.version import build_info

app = typer.Typer(
    name="germandubi",
    help="German Dub Interface - turn English videos into editable German dubs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
errors = Console(stderr=True)


def _settings() -> Settings:
    """Return the process settings with logging configured."""
    settings = get_settings()
    configure_logging(settings)
    return settings


def _fail(message: str) -> None:
    """Print an error and exit with a non-zero status."""
    errors.print(f"[bold red]error:[/] {message}")
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the build version and the revision it came from."""
    info = build_info()
    console.print(f"GermanDubI {info.display}")


@app.command()
def doctor() -> None:
    """Check that everything needed to produce a dub is installed."""
    settings = _settings()
    application = build_application(settings, create_schema=False)
    report = application.registry.report()

    tools = Table(title="External tools", show_header=True, header_style="bold")
    tools.add_column("Tool")
    tools.add_column("Status")
    for name, found in sorted(report.tools.items()):
        tools.add_row(name, "[green]found[/]" if found else "[red]missing[/]")
    console.print(tools)

    providers = Table(title="Providers", show_header=True, header_style="bold")
    providers.add_column("Provider")
    providers.add_column("Type")
    providers.add_column("Status")
    providers.add_column("Notes", overflow="fold")
    for info, available in report.providers:
        providers.add_row(
            info.name,
            "[yellow]network[/]" if str(info.kind) == "network" else "local",
            "[green]ready[/]" if available else "[dim]not installed[/]",
            info.notes or "",
        )
    console.print(providers)

    device = "GPU (cuda)" if report.device == "cuda" else "CPU"
    console.print(f"\nCompute:      [cyan]{device}[/]")
    console.print(f"Project data: [cyan]{report.data_dir}[/]")
    console.print(f"Writable:     {'[green]yes[/]' if report.writable else '[red]no[/]'}")
    # Printed here because this is the command people are told to run when something is
    # wrong, and the log is the next thing they will be asked for.
    log_file = settings.resolved_log_file
    console.print(f"Server log:   [cyan]{log_file or 'console only'}[/]")

    application.dispose()

    if report.missing_required:
        _fail(
            f"missing required tools: {', '.join(report.missing_required)}. "
            f"Install them and run this again."
        )
    if not report.writable:
        _fail(f"cannot write to {report.data_dir}")
    if report.missing_for_a_real_dub:
        errors.print(
            "\n[bold yellow]Not ready to dub.[/] These produce placeholder output, not "
            "German:\n  " + "\n  ".join(report.missing_for_a_real_dub)
        )
        errors.print("\nInstall them with `make install-providers`, then run this again.")
        raise typer.Exit(code=1)
    console.print("\n[green]Ready to dub.[/]")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address.")] = None,
    port: Annotated[int | None, typer.Option(help="Port to listen on.")] = None,
    reload: Annotated[bool, typer.Option(help="Reload on source changes.")] = False,
) -> None:
    """Run the HTTP API and serve the compiled frontend if it is present."""
    settings = _settings()
    uvicorn.run(
        "germandubi.api.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def worker(
    once: Annotated[bool, typer.Option(help="Process the queue once, then exit.")] = False,
) -> None:
    """Run the processing worker."""
    settings = _settings()
    application = build_application(settings)
    process = application.worker()

    if once:
        executed = process.run_until_idle()
        console.print(f"processed {executed} job(s)")
        application.dispose()
        return

    process.install_signal_handlers()
    try:
        # One worker per data directory. Two would claim different jobs of the same run and
        # write into the same workspace without either knowing.
        with process.exclusive():
            process.run_forever()
    except ResourceError as error:
        application.dispose()
        _fail(error.message)
    finally:
        application.dispose()


@app.command()
def dub(
    source: Annotated[str, typer.Argument(help="A YouTube URL or a path to a local file.")],
    quality: Annotated[
        QualityProfile, typer.Option(help="Speed/quality trade-off.")
    ] = QualityProfile.BALANCED,
) -> None:
    """Dub a source end to end in this process, without the browser.

    Useful for scripting and for reproducing a pipeline failure with a stack trace.
    """
    settings = _settings()
    application = build_application(settings)
    try:
        project = (
            application.projects.create_from_file(str(Path(source).resolve()), quality=quality)
            if Path(source).exists()
            else application.projects.create_from_url(source, quality=quality)
        )
        console.print(f"project [cyan]{project.id}[/]")

        process = application.worker()
        application.projects.request_analysis(project.id)
        process.run_until_idle()

        analysed = application.projects.get(project.id)
        if analysed.media is None:
            _fail(analysed.error or "the source could not be analysed")
        console.print(f"source: [bold]{analysed.display_title}[/]")

        application.pipeline.start(project.id)
        process.run_until_idle()
        _print_progress(application.pipeline.latest_progress(project.id))

        with application.unit_of_work() as uow:
            export = uow.artifacts.latest(project.id, ArtifactKind.EXPORT)
            if export is None:
                _fail("the run finished without producing an export")
            else:
                console.print(f"\n[green]exported:[/] {uow.store.path_for(export)}")
    except GermanDubIError as exc:
        _fail(exc.message)
    finally:
        application.dispose()


@app.command()
def inspect(
    project_id: Annotated[str, typer.Argument(help="The project identifier.")],
) -> None:
    """Show a project's state, stages and segment counts."""
    settings = _settings()
    application = build_application(settings, create_schema=False)
    try:
        identity = ProjectId(Ulid(project_id))
    except ValueError:
        application.dispose()
        _fail(f"{project_id!r} is not a valid project identifier")
        return

    try:
        project = application.projects.get(identity)
        console.print(f"[bold]{project.display_title}[/]")
        console.print(f"state:  {project.state}")
        console.print(f"source: {project.source.locator}")
        if project.error:
            console.print(f"[red]error:[/] {project.error}")

        _print_progress(application.pipeline.latest_progress(identity))

        summary = application.segments.summary(identity)
        console.print(
            f"\nsegments: {summary.total} total, {summary.translated} translated, "
            f"{summary.synthesized} synthesized, {summary.approved} approved, "
            f"{summary.flagged} flagged"
        )
    except GermanDubIError as exc:
        _fail(exc.message)
    finally:
        application.dispose()


@app.command(name="list")
def list_projects() -> None:
    """List projects, newest first."""
    settings = _settings()
    application = build_application(settings, create_schema=False)
    projects = application.projects.list_projects(limit=50)
    application.dispose()

    if not projects:
        console.print("[dim]no projects yet[/]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Id")
    table.add_column("State")
    table.add_column("Title", overflow="fold")
    for project in projects:
        table.add_row(str(project.id), str(project.state), project.display_title)
    console.print(table)


def _print_progress(progress: RunProgress | None) -> None:
    """Print a run's stages and their outcomes."""
    if progress is None:
        console.print("[dim]this project has never been processed[/]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for job in progress.jobs:
        colour = {
            "succeeded": "green",
            "failed": "red",
            "running": "yellow",
            "cancelled": "magenta",
        }.get(str(job.status), "dim")
        table.add_row(
            job.stage.label,
            f"[{colour}]{job.status}[/]",
            job.error or job.progress_detail or "",
        )
    console.print(table)


def main() -> None:
    """Entry point used by the console script."""
    try:
        app()
    except GermanDubIError as exc:
        errors.print(f"[bold red]error:[/] {exc.message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
