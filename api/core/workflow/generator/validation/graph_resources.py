"""graph resources."""

from typing import Any

from core.workflow.generator.compiler.agent_knowledge import collect_agent_knowledge_dataset_ids
from core.workflow.generator.types import (
    WorkflowGenerateErrorCode,
    WorkflowGenerateErrorDict,
)
from core.workflow.generator.validation.graph_validation_values import _err
from graphon.enums import BuiltinNodeTypes


def _collect_unknown_tools(
    *,
    nodes: list[dict[str, Any]],
    installed_tools: set[tuple[str, str]],
) -> list[WorkflowGenerateErrorDict]:
    """Flag tool nodes naming a provider / tool pair not in the catalogue."""
    out: list[WorkflowGenerateErrorDict] = []
    for n in nodes:
        data = n.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.TOOL:
            continue
        # The builder is told to put the catalogue's ``provider_name``
        # into BOTH ``provider_id`` and ``provider_name``. Accept either
        # for the lookup so we don't false-fail on the rare case where
        # the LLM only populated one of the two fields.
        provider = str(data.get("provider_id") or data.get("provider_name") or "").strip()
        tool = str(data.get("tool_name") or "").strip()
        if not provider or not tool:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                    f"Tool node {n.get('id')!r} missing provider / tool name",
                    node_id=n.get("id", ""),
                )
            )
            continue
        if (provider, tool) not in installed_tools:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                    f"Tool {provider}/{tool} is not installed for this tenant",
                    node_id=n.get("id", ""),
                )
            )
    out.extend(_collect_unknown_dify_tools(nodes=nodes, installed_tools=installed_tools))
    return out


def _collect_unknown_dify_tools(
    *,
    nodes: list[dict[str, Any]],
    installed_tools: set[tuple[str, str]],
) -> list[WorkflowGenerateErrorDict]:
    """Flag agent nodes whose Soul dify_tools are outside the catalogue."""
    out: list[WorkflowGenerateErrorDict] = []
    providers = {item[0] for item in installed_tools}
    for n in nodes:
        data = n.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.AGENT:
            continue
        dify_tools = data.get("dify_tools")
        if not isinstance(dify_tools, list):
            continue
        for item in dify_tools:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider_id") or item.get("provider_name") or item.get("provider") or "").strip()
            tool_name = item.get("tool_name")
            if not provider:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                        f"Agent node {n.get('id')!r} dify_tools entry missing provider",
                        node_id=n.get("id", ""),
                    )
                )
                continue
            if tool_name is None or tool_name == "":
                if provider not in providers:
                    out.append(
                        _err(
                            WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                            f"Tool {provider} is not installed for this tenant",
                            node_id=n.get("id", ""),
                        )
                    )
                continue
            tool = str(tool_name).strip()
            if (provider, tool) not in installed_tools:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                        f"Tool {provider}/{tool} is not installed for this tenant",
                        node_id=n.get("id", ""),
                    )
                )
    return out


def _collect_unknown_dataset_ids(
    *,
    nodes: list[dict[str, Any]],
    installed_dataset_ids: set[str] | None,
) -> list[WorkflowGenerateErrorDict]:
    """Require valid dataset ids and optionally verify tenant membership."""
    out: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        node_type = data.get("type")
        if node_type == BuiltinNodeTypes.AGENT:
            dataset_ids = collect_agent_knowledge_dataset_ids(data)
            if installed_dataset_ids is None:
                continue
            unknown_ids = sorted(dataset_id for dataset_id in dataset_ids if dataset_id not in installed_dataset_ids)
            if unknown_ids:
                out.append(
                    _err(
                        WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                        f"Agent node {node.get('id')!r} references uninstalled datasets: {', '.join(unknown_ids)}",
                        node_id=node.get("id", ""),
                    )
                )
            continue
        if node_type != BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
            continue
        dataset_ids = data.get("dataset_ids")
        if not isinstance(dataset_ids, list) or not dataset_ids:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                    f"Knowledge-retrieval node {node.get('id')!r} must define a non-empty dataset_ids list",
                    node_id=node.get("id", ""),
                )
            )
            continue
        invalid_ids = [
            dataset_id for dataset_id in dataset_ids if not isinstance(dataset_id, str) or not dataset_id.strip()
        ]
        if invalid_ids:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                    f"Knowledge-retrieval node {node.get('id')!r} contains invalid dataset ids",
                    node_id=node.get("id", ""),
                )
            )
            continue
        if installed_dataset_ids is None:
            continue
        unknown_ids = sorted(dataset_id for dataset_id in dataset_ids if dataset_id not in installed_dataset_ids)
        if unknown_ids:
            out.append(
                _err(
                    WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                    f"Knowledge-retrieval node {node.get('id')!r} references uninstalled datasets: "
                    f"{', '.join(unknown_ids)}",
                    node_id=node.get("id", ""),
                )
            )
    return out


def _collect_unknown_tool_parameters(
    *,
    nodes: list[dict[str, Any]],
    tool_parameter_names: dict[tuple[str, str], frozenset[str]] | None,
) -> list[WorkflowGenerateErrorDict]:
    if tool_parameter_names is None:
        return []
    out: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.TOOL:
            continue
        provider = str(data.get("provider_id") or data.get("provider_name") or "").strip()
        tool_name = str(data.get("tool_name") or "").strip()
        allowed = tool_parameter_names.get((provider, tool_name))
        if allowed is None:
            continue
        parameters = data.get("tool_parameters")
        if not isinstance(parameters, dict):
            continue
        unknown = sorted(key for key in parameters if isinstance(key, str) and key not in allowed)
        if not unknown:
            continue
        out.append(
            _err(
                WorkflowGenerateErrorCode.INVALID_SCHEMA,
                f"Tool node {node.get('id')!r} has unknown parameters: {', '.join(unknown)}",
                node_id=str(node.get("id") or ""),
            )
        )
    return out
