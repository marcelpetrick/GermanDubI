"""Executable architecture rules.

AGENTS.md states the layering rules; this file is what makes them true. A rule that is only
written down erodes silently, one convenient import at a time.

Do not weaken these tests to make a change pass. If a rule is genuinely wrong, change the
rule in AGENTS.md and write an ADR explaining why.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

from germandubi.domain.entities.pipeline import STAGE_DEPENDENCIES, Stage
from germandubi.worker.handlers import HANDLERS

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "backend" / "src" / "germandubi"


#: Files nobody hand-writes, so the rules below do not apply to them.
GENERATED = {"_version.py"}


def modules_under(package: str) -> list[Path]:
    """Return every hand-written Python module in a package of the application."""
    root = SOURCE_ROOT / package if package else SOURCE_ROOT
    return sorted(
        p for p in root.rglob("*.py") if "migrations" not in p.parts and p.name not in GENERATED
    )


def imports_of(path: Path) -> set[str]:
    """Return every module name imported by a file, including inside functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def relative(path: Path) -> str:
    """Return a short, readable path for assertion messages."""
    return str(path.relative_to(SOURCE_ROOT.parent.parent))


class TestDomainPurity:
    """The domain layer depends on the standard library and nothing else."""

    FORBIDDEN: ClassVar[tuple[str, ...]] = (
        "fastapi",
        "starlette",
        "sqlalchemy",
        "alembic",
        "pydantic",
        "uvicorn",
        "yt_dlp",
        "faster_whisper",
        "argostranslate",
        "piper",
        "demucs",
        "torch",
        "httpx",
        "typer",
    )

    @pytest.mark.parametrize("module", modules_under("domain"), ids=relative)
    def test_domain_imports_no_third_party_library(self, module: Path) -> None:
        offending = {
            name
            for name in imports_of(module)
            for forbidden in self.FORBIDDEN
            if name == forbidden or name.startswith(f"{forbidden}.")
        }
        assert not offending, f"{relative(module)} imports {sorted(offending)}"

    @pytest.mark.parametrize("module", modules_under("domain"), ids=relative)
    def test_domain_does_not_import_other_layers(self, module: Path) -> None:
        offending = {
            name
            for name in imports_of(module)
            if name.startswith(
                (
                    "germandubi.infrastructure",
                    "germandubi.api",
                    "germandubi.worker",
                    "germandubi.application",
                    "germandubi.cli",
                )
            )
        }
        assert not offending, f"{relative(module)} imports {sorted(offending)}"


class TestApplicationBoundaries:
    """The application layer depends on ports, not on provider implementations."""

    @pytest.mark.parametrize("module", modules_under("application/ports"), ids=relative)
    def test_ports_do_not_import_infrastructure(self, module: Path) -> None:
        """A port that imports its implementation is not a port."""
        offending = {
            name for name in imports_of(module) if name.startswith("germandubi.infrastructure")
        }
        assert not offending, f"{relative(module)} imports {sorted(offending)}"

    @pytest.mark.parametrize("module", modules_under("application"), ids=relative)
    def test_application_does_not_import_the_api_or_the_cli(self, module: Path) -> None:
        offending = {
            name
            for name in imports_of(module)
            if name.startswith(("germandubi.api", "germandubi.cli"))
        }
        assert not offending, f"{relative(module)} imports {sorted(offending)}"

    @pytest.mark.parametrize("module", modules_under("application"), ids=relative)
    def test_application_does_not_import_a_concrete_provider(self, module: Path) -> None:
        offending = {
            name
            for name in imports_of(module)
            if name.startswith("germandubi.infrastructure.providers")
        }
        assert not offending, f"{relative(module)} imports {sorted(offending)}"


class TestProcessBoundary:
    """Only the process runner may spawn external processes."""

    ALLOWED: ClassVar[set[str]] = {"infrastructure/processes/runner.py"}

    @pytest.mark.parametrize("module", modules_under(""), ids=relative)
    def test_subprocess_is_imported_only_by_the_runner(self, module: Path) -> None:
        relative_path = module.relative_to(SOURCE_ROOT).as_posix()
        if relative_path in self.ALLOWED:
            return
        offending = {
            name for name in imports_of(module) if name in {"subprocess", "os.system", "commands"}
        }
        assert not offending, (
            f"{relative(module)} imports {sorted(offending)}; all external processes must go "
            f"through germandubi.infrastructure.processes.runner"
        )

    def test_the_runner_is_the_only_place_calling_popen(self) -> None:
        callers = [
            relative(module)
            for module in modules_under("")
            if module.relative_to(SOURCE_ROOT).as_posix() not in self.ALLOWED
            and "subprocess.Popen" in module.read_text(encoding="utf-8")
        ]
        assert not callers, f"these modules call Popen directly: {callers}"


class TestInfrastructureIsolation:
    """Infrastructure implements ports; it does not reach back into the API."""

    @pytest.mark.parametrize("module", modules_under("infrastructure"), ids=relative)
    def test_infrastructure_does_not_import_the_api(self, module: Path) -> None:
        offending = {name for name in imports_of(module) if name.startswith("germandubi.api")}
        assert not offending, f"{relative(module)} imports {sorted(offending)}"


class TestPipelineCompleteness:
    """The stage graph and the handler registry must agree."""

    def test_every_stage_has_a_handler(self) -> None:
        missing = set(Stage) - set(HANDLERS)
        assert not missing, f"stages with no handler: {sorted(missing)}"

    def test_no_handler_is_registered_for_an_unknown_stage(self) -> None:
        assert set(HANDLERS) <= set(Stage)

    def test_every_stage_declares_dependencies(self) -> None:
        assert set(STAGE_DEPENDENCIES) == set(Stage)


class TestDocumentation:
    """Public application and domain APIs carry docstrings."""

    @pytest.mark.parametrize(
        "module", modules_under("domain") + modules_under("application"), ids=relative
    )
    def test_public_functions_and_classes_are_documented(self, module: Path) -> None:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        undocumented = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and not node.name.startswith("_")
            and ast.get_docstring(node) is None
        ]
        assert not undocumented, f"{relative(module)}: {undocumented} lack docstrings"

    @pytest.mark.parametrize("module", modules_under(""), ids=relative)
    def test_every_module_has_a_docstring(self, module: Path) -> None:
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        assert ast.get_docstring(tree) is not None, f"{relative(module)} has no module docstring"
