"""Expose the generator-visible tool catalogue for workflow-assist UI."""

from __future__ import annotations

from typing import Any, TypedDict

from core.workflow.generator.tool_catalogue import (
    _MAX_TOOLS,
    ToolCatalogueEntry,
    build_tool_catalogue,
)


class AssistToolCatalogue(TypedDict):
    tools: list[ToolCatalogueEntry]
    truncated: bool
    max_tools: int
    total_before_cap: int


def list_assist_tool_catalogue(tenant_id: str) -> AssistToolCatalogue:
    """
    Return the same installed-tool inventory the planner/builder sees.

    Fetches the uncapped catalogue, then applies the generator's ``_MAX_TOOLS``
    cap so the UI can show ``truncated`` when tools were dropped.
    """
    all_tools = build_tool_catalogue(tenant_id, limit=None)
    total_before_cap = len(all_tools)
    max_tools = _MAX_TOOLS
    truncated = total_before_cap > max_tools
    tools: list[ToolCatalogueEntry] = all_tools[:max_tools]
    return AssistToolCatalogue(
        tools=tools,
        truncated=truncated,
        max_tools=max_tools,
        total_before_cap=total_before_cap,
    )


def list_assist_tool_catalogue_as_dict(tenant_id: str) -> dict[str, Any]:
    """JSON-serializable form of :func:`list_assist_tool_catalogue`."""
    return dict(list_assist_tool_catalogue(tenant_id))
