"""Tenant resource facts shared by HTTP and Apply; core remains I/O-free."""

import json
from typing import NotRequired, TypedDict

from core.workflow.generator.compiler.agent_knowledge import collect_agent_knowledge_dataset_ids
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.resources.tool_catalogue import (
    ToolCatalogueEntry,
    installed_tool_keys,
    tool_schema_lookups,
)
from core.workflow.generator.types import GraphDict
from models.workflow import Workflow
from services.workflow_assist.knowledge_catalogue_loader import build_knowledge_catalogue
from services.workflow_assist.model_catalogue import build_agent_model_catalogue
from services.workflow_assist.tool_catalogue_loader import build_tool_catalogue


class WorkflowValidationContext(TypedDict):
    tool_entries: NotRequired[list[ToolCatalogueEntry]]
    installed_tools: NotRequired[set[tuple[str, str]]]
    installed_dataset_ids: NotRequired[set[str]]
    installed_models: NotRequired[set[tuple[str, str]]]
    environment_variables: NotRequired[set[str]]
    conversation_variables: NotRequired[set[str]]
    tool_parameter_names: NotRequired[dict[tuple[str, str], frozenset[str]]]
    tool_output_names: NotRequired[dict[tuple[str, str], frozenset[str]]]


def namespace_names(raw: str) -> set[str]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("Draft variable namespace must be an object")
    return {v["name"] for v in payload.values() if isinstance(v, dict) and isinstance(v.get("name"), str) and v["name"]}


def build_validation_context(
    *,
    tenant_id: str,
    graph: MinimalGraphDict | GraphDict,
    draft: Workflow | None,
    include_models: bool = False,
) -> WorkflowValidationContext:
    """Load only required resource families; propagate failures instead of skipping checks."""
    result: WorkflowValidationContext = {}
    raw_nodes = graph.get("nodes", [])
    data = [n.get("data") or {} for n in raw_nodes if isinstance(n, dict)] if isinstance(raw_nodes, list) else []
    if any(
        isinstance(d, dict)
        and (
            d.get("type") == "tool"
            or d.get("dify_tools")
            or (isinstance(d.get("assist_binding_manifest"), dict) and d["assist_binding_manifest"].get("tool_keys"))
        )
        for d in data
    ):
        entries = build_tool_catalogue(tenant_id, limit=None, raise_on_error=True)
        result["tool_entries"] = entries
        result["installed_tools"] = installed_tool_keys(entries)
        result["tool_parameter_names"], result["tool_output_names"] = tool_schema_lookups(entries)
    if any(
        isinstance(d, dict)
        and (
            d.get("type") == "knowledge-retrieval"
            or bool(collect_agent_knowledge_dataset_ids(d))
            or (isinstance(d.get("assist_binding_manifest"), dict) and d["assist_binding_manifest"].get("dataset_ids"))
        )
        for d in data
    ):
        result["installed_dataset_ids"] = {
            entry["id"] for entry in build_knowledge_catalogue(tenant_id, limit=None, raise_on_error=True)
        }
    if include_models and any(
        isinstance(d, dict)
        and isinstance(d.get("model"), dict)
        and d["model"].get("provider")
        and d["model"].get("name")
        for d in data
    ):
        result["installed_models"] = {
            (entry["provider"], entry["name"]) for entry in build_agent_model_catalogue(tenant_id)
        }
    if draft is not None:
        result["environment_variables"] = namespace_names(draft._environment_variables or "{}")
        result["conversation_variables"] = namespace_names(draft._conversation_variables or "{}")
    return result
