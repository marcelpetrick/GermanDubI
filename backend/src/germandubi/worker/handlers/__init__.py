"""Stage handlers, one per pipeline stage.

Each handler takes a :class:`~germandubi.worker.context.StageContext` and returns nothing;
its effect is the artifacts it writes and the state it records. Handlers are registered in
:data:`HANDLERS` and dispatched by the planner, so adding a stage means adding a handler and
declaring its dependencies - never editing a long conditional.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from germandubi.domain.entities.pipeline import Stage
from germandubi.worker.context import StageContext
from germandubi.worker.handlers.audio import (
    handle_assemble,
    handle_mix,
    handle_separate,
    handle_subtitle,
)
from germandubi.worker.handlers.german import (
    handle_fit,
    handle_prosody,
    handle_synthesize,
    handle_translate,
)
from germandubi.worker.handlers.output import handle_export, handle_qa
from germandubi.worker.handlers.source import handle_acquire, handle_normalize, handle_probe
from germandubi.worker.handlers.transcript import (
    handle_align,
    handle_segment,
    handle_transcribe,
)

__all__ = ["HANDLERS", "StageHandler"]

StageHandler = Callable[[StageContext], None]

#: Every stage must appear here; a completeness test asserts it.
HANDLERS: Final[dict[Stage, StageHandler]] = {
    Stage.PROBE: handle_probe,
    Stage.ACQUIRE: handle_acquire,
    Stage.NORMALIZE: handle_normalize,
    Stage.TRANSCRIBE: handle_transcribe,
    Stage.ALIGN: handle_align,
    Stage.SEGMENT: handle_segment,
    Stage.SEPARATE: handle_separate,
    Stage.TRANSLATE: handle_translate,
    Stage.PROSODY: handle_prosody,
    Stage.SYNTHESIZE: handle_synthesize,
    Stage.FIT: handle_fit,
    Stage.ASSEMBLE: handle_assemble,
    Stage.MIX: handle_mix,
    Stage.SUBTITLE: handle_subtitle,
    Stage.QA: handle_qa,
    Stage.EXPORT: handle_export,
}
