"""Deterministic Agent V2 config compiler.

Writes version/kind/inline binding, copies catalogue tool identity and the
model-visible parameter schema, and projects knowledge through
``compile_agent_knowledge``. Does not write the database or hydrate bindings.
"""

from __future__ import annotations

from typing import Any

from core.workflow.generator.compiler.agent_knowledge import (
    agent_knowledge_intent_dataset_ids,
    apply_agent_knowledge_intent,
    collect_agent_knowledge_dataset_ids,
)
from core.workflow.generator.compiler.intents.agent_intent import AgentBindingManifest, AgentNodeBuildIntent
from core.workflow.generator.compiler.intents.tool_intent import ToolBinding
from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, find_tool_entry
from core.workflow.generator.variables.variable_registry import VariableRegistry, VariableResolutionError


class AgentNodeConfigError(ValueError):
    """A stable, user-safe failure raised by deterministic Agent compilation."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def compile_agent_node_config(
    *,
    intent: AgentNodeBuildIntent,
    tool_entries: list[ToolCatalogueEntry],
    knowledge_entries: list[KnowledgeCatalogueEntry],
    variable_registry: VariableRegistry,
    referrer_id: str,
    mode: str,
    old_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], AgentBindingManifest]:
    """Compile Agent V2 node data and a declarative binding manifest.

    The manifest is copied onto node data as ``assist_binding_manifest`` so the
    service layer can re-resolve tools and datasets. It carries no credentials
    and is not an authorization token.
    """
    for item in intent.inputs:
        try:
            variable_registry.resolve(item.source, referrer_id=referrer_id, expected_type=None)
        except VariableResolutionError as exc:
            raise AgentNodeConfigError(exc.code, exc.detail) from exc

    dify_tools, tool_keys = _compile_dify_tools(intent, tool_entries)
    config: dict[str, Any] = {
        "version": "2",
        "agent_node_kind": "dify_agent",
        "agent_task": _render_agent_task(intent),
        "agent_binding": {"binding_type": "inline_agent"},
        "model": _compile_model(intent),
        "dify_tools": dify_tools,
    }
    if intent.outputs:
        config["agent_declared_outputs"] = [
            {"name": output.name, "type": output.type or "string"} for output in intent.outputs
        ]

    try:
        apply_agent_knowledge_intent(
            mode=mode,
            config=config,
            old_config=old_config or {},
            intent=intent.knowledge,
            catalogue_entries=knowledge_entries,
        )
    except ValueError as exc:
        raise AgentNodeConfigError("UNKNOWN_DATASET", str(exc)) from exc

    dataset_ids = tuple(agent_knowledge_intent_dataset_ids(intent.knowledge)) if intent.knowledge is not None else ()
    if intent.knowledge is None and mode == "update" and isinstance((old_config or {}).get("knowledge"), dict):
        dataset_ids = tuple(collect_agent_knowledge_dataset_ids(old_config or {}))

    manifest = AgentBindingManifest(
        binding_id=referrer_id,
        tool_keys=tool_keys,
        dataset_ids=dataset_ids,
    )
    config["assist_binding_manifest"] = {
        "binding_id": manifest.binding_id,
        "tool_keys": [list(pair) for pair in manifest.tool_keys],
        "dataset_ids": list(manifest.dataset_ids),
    }
    return config, manifest


def _compile_model(intent: AgentNodeBuildIntent) -> dict[str, Any]:
    model: dict[str, Any] = {
        "provider": intent.model.provider,
        "name": intent.model.name,
        "mode": intent.model.mode,
    }
    if intent.model.completion_params is not None:
        model["completion_params"] = dict(intent.model.completion_params)
    return model


def _render_agent_task(intent: AgentNodeBuildIntent) -> str:
    if not intent.inputs:
        return intent.instruction
    lines = [intent.instruction, "", "Inputs:"]
    for item in intent.inputs:
        selector = ".".join(item.source)
        lines.append(f"- {item.role}: {{{{#{selector}#}}}}")
    return "\n".join(lines)


def _compile_dify_tools(
    intent: AgentNodeBuildIntent,
    tool_entries: list[ToolCatalogueEntry],
) -> tuple[list[dict[str, Any]], tuple[tuple[str, str], ...]]:
    compiled: list[dict[str, Any]] = []
    keys: list[tuple[str, str]] = []
    for binding in intent.tools:
        entry = _require_entry(binding, tool_entries, expected_type="mcp", invert=True)
        compiled.append(_dify_tool_from_entry(entry))
        keys.append((entry["provider_name"], entry["tool_name"]))
    for binding in intent.mcp_tools:
        entry = _require_entry(binding, tool_entries, expected_type="mcp", invert=False)
        compiled.append(_dify_tool_from_entry(entry))
        keys.append((entry["provider_name"], entry["tool_name"]))
    return compiled, tuple(keys)


def _require_entry(
    binding: ToolBinding,
    tool_entries: list[ToolCatalogueEntry],
    *,
    expected_type: str,
    invert: bool,
) -> ToolCatalogueEntry:
    entry = find_tool_entry(
        tool_entries,
        provider_name=binding.provider_name,
        tool_name=binding.tool_name,
    )
    if entry is None:
        raise AgentNodeConfigError(
            "UNKNOWN_TOOL",
            f"Tool {binding.provider_name}/{binding.tool_name} is not present in the current catalogue",
        )
    is_expected = entry["provider_type"] == expected_type
    if invert:
        is_expected = not is_expected
    if not is_expected:
        raise AgentNodeConfigError(
            "UNKNOWN_TOOL",
            f"Tool {binding.provider_name}/{binding.tool_name} is not present in the current catalogue",
        )
    return entry


def _dify_tool_from_entry(entry: ToolCatalogueEntry) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": True,
        "provider_type": entry["provider_type"],
        "provider_id": entry["provider_name"],
        "tool_name": entry["tool_name"],
        "credential_type": "unauthorized",
        "description": entry["description"],
    }
    plugin_id = entry.get("plugin_id")
    if plugin_id:
        payload["plugin_id"] = plugin_id
    if "parameters" not in entry:
        raise AgentNodeConfigError(
            "TOOL_SCHEMA_UNAVAILABLE",
            f"Tool {entry['provider_name']}/{entry['tool_name']} has no readable parameter schema",
        )
    parameters = [
        {
            "name": spec["name"],
            "type": spec["type"],
            "required": spec["required"],
        }
        for spec in entry["parameters"]
    ]
    if parameters:
        payload["parameters"] = parameters
    return payload
