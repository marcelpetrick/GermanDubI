"""Server-sent progress events.

Communication here is almost entirely server-to-browser, so SSE is a better fit than a
WebSocket: it reconnects on its own, it survives a proxy, and it needs no protocol of our
own (ADR-0005).

Events are persisted with a monotonic sequence number, so a browser that reconnects sends
``Last-Event-ID`` and receives exactly what it missed. That is what makes refreshing the
page mid-processing harmless.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Final

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from germandubi.api.dependencies import AppDep, ProjectIdDep
from germandubi.composition import Application
from germandubi.domain.value_objects.identifiers import ProjectId

router = APIRouter(prefix="/projects/{project_id}/events", tags=["events"])

logger = logging.getLogger(__name__)

#: How often to look for new events. The worker writes to SQLite rather than notifying us,
#: so this is a poll; a quarter of a second is imperceptible in a UI and cheap on an
#: indexed query.
_POLL_INTERVAL_S: Final = 0.25
#: A comment line often enough to keep proxies and browsers from timing the stream out.
_KEEPALIVE_S: Final = 15.0
_MAX_BATCH: Final = 200


def _format(sequence: int, kind: str, payload: dict[str, object]) -> str:
    """Render one event in the SSE wire format."""
    body = json.dumps(payload, default=str)
    return f"id: {sequence}\nevent: {kind}\ndata: {body}\n\n"


async def _stream(
    app: Application, project_id: ProjectId, request: Request, after: int, *, lifetime_s: float
) -> AsyncIterator[str]:
    """Yield events for a project until the client disconnects or the stream ages out.

    The lifetime bound matters for two reasons. A disconnect is not always detectable
    promptly, so an unbounded generator can outlive its client and accumulate; and SSE
    clients reconnect on their own, replaying from ``Last-Event-ID``, so closing costs the
    user nothing.

    Args:
        app: The wired application.
        project_id: The project to follow.
        request: Used to notice a disconnect promptly.
        after: Resume from this sequence number.
        lifetime_s: How long to keep the stream open.

    Yields:
        SSE-formatted event frames.
    """
    cursor = after
    since_keepalive = 0.0
    deadline = time.monotonic() + lifetime_s

    # Tell the browser how long to wait before reconnecting, and confirm the stream is open.
    yield "retry: 2000\n\n"

    while time.monotonic() < deadline and not await request.is_disconnected():
        with app.unit_of_work() as uow:
            batch = uow.events.since(project_id, after=cursor, limit=_MAX_BATCH)

        if batch:
            for sequence, kind, payload in batch:
                cursor = sequence
                yield _format(sequence, kind, payload)
            since_keepalive = 0.0
        else:
            await asyncio.sleep(_POLL_INTERVAL_S)
            since_keepalive += _POLL_INTERVAL_S
            if since_keepalive >= _KEEPALIVE_S:
                yield ": keepalive\n\n"
                since_keepalive = 0.0

    logger.debug("event stream for project %s closed", project_id)


@router.get(
    "",
    summary="Progress event stream",
    description=(
        "A `text/event-stream` of pipeline progress. Send `Last-Event-ID` to resume after a "
        "reconnect and receive exactly the events you missed."
    ),
    response_class=StreamingResponse,
    operation_id="streamEvents",
)
async def stream_events(
    project_id: ProjectIdDep,
    request: Request,
    app: AppDep,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Stream a project's progress events.

    Args:
        project_id: The project to follow.
        request: The incoming request.
        app: The wired application.
        last_event_id: The last sequence number the client received.

    Returns:
        The event stream.
    """
    try:
        after = int(last_event_id) if last_event_id else 0
    except ValueError:
        after = 0

    return StreamingResponse(
        _stream(app, project_id, request, after, lifetime_s=app.settings.sse_stream_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Without this, nginx buffers the stream and progress arrives in one lump.
            "X-Accel-Buffering": "no",
        },
    )
