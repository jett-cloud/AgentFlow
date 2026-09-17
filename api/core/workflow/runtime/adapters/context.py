"""context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from core.app.entities.app_invoke_entities import DIFY_RUN_CONTEXT_KEY, DifyRunContext

if TYPE_CHECKING:
    pass


def resolve_dify_run_context(run_context: Mapping[str, Any] | DifyRunContext) -> DifyRunContext:
    if isinstance(run_context, DifyRunContext):
        return run_context

    raw_ctx = run_context.get(DIFY_RUN_CONTEXT_KEY)
    if raw_ctx is None:
        raise ValueError(f"run_context missing required key: {DIFY_RUN_CONTEXT_KEY}")
    if isinstance(raw_ctx, DifyRunContext):
        return raw_ctx
    return DifyRunContext.model_validate(raw_ctx)
