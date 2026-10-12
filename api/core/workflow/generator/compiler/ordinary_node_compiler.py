"""Compatibility wrapper for deterministic ordinary-node compilation."""

from __future__ import annotations

from typing import Any

from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent
from core.workflow.generator.compiler.node_compile_context import NodeCompileContext
from core.workflow.generator.compiler.node_intent_compiler import compile_node_intent


def compile_structured_node_config(
    *,
    intent: NodeBuildIntent,
    builder_config: dict[str, Any],
    context: NodeCompileContext | None = None,
) -> dict[str, Any]:
    """Compile through the unified dispatcher while preserving the old API."""
    compile_context = context or NodeCompileContext(
        node_id="_ordinary_node",
        surface="top_level",
        mode="create",
    )
    return compile_node_intent(intent=intent, context=compile_context, base_config=builder_config)


__all__ = ["compile_structured_node_config"]
