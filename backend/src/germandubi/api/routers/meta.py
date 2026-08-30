"""Build identity and environment health."""

from __future__ import annotations

from fastapi import APIRouter

from germandubi.api.dependencies import AppDep
from germandubi.api.schemas import HealthResponse, MetaResponse, ProviderStatus
from germandubi.domain.value_objects.language import SOURCE_LANGUAGE, TARGET_LANGUAGE
from germandubi.version import build_info

router = APIRouter(tags=["meta"])


@router.get(
    "/meta",
    response_model=MetaResponse,
    summary="Build identity",
    description="Which source revision produced this running build, and what it can dub.",
    operation_id="getMeta",
)
async def get_meta() -> MetaResponse:
    """Return the running build's identity.

    Returns:
        Version, revision and the supported language pair.
    """
    info = build_info()
    return MetaResponse(
        application="germandubi",
        version=info.version,
        display_version=info.display,
        api_version="v1",
        git_revision=info.git_revision,
        dirty=info.dirty,
        source_language=str(SOURCE_LANGUAGE),
        target_language=str(TARGET_LANGUAGE),
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Environment health",
    description="Whether the external tools this application needs are present and usable.",
    operation_id="getHealth",
)
async def get_health(app: AppDep) -> HealthResponse:
    """Report whether the environment can actually produce a dub.

    Args:
        app: The wired application.

    Returns:
        Tool availability and the data directory's writability.
    """
    report = app.registry.report()
    return HealthResponse(
        status="ok" if report.can_dub and report.writable else "degraded",
        tools=report.tools,
        missing=report.missing_required,
        data_dir=str(report.data_dir),
        writable=report.writable,
    )


@router.get(
    "/providers",
    response_model=list[ProviderStatus],
    summary="Provider availability",
    description=(
        "Which model providers are installed. A provider of kind `network` sends data off "
        "this machine and is never selected unless explicitly allowed."
    ),
    operation_id="listProviders",
)
async def list_providers(app: AppDep) -> list[ProviderStatus]:
    """Return every known provider and whether it can run.

    Args:
        app: The wired application.

    Returns:
        The provider statuses.
    """
    return [
        ProviderStatus(
            id=info.id,
            name=info.name,
            kind="network" if str(info.kind) == "network" else "local",
            model_id=info.model_id,
            available=available,
            notes=info.notes,
        )
        for info, available in app.registry.report().providers
    ]
