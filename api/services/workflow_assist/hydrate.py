"""Hydrate generated Agent v2 nodes without persisting workflow draft graphs.

This module only creates the backing Agent and snapshot rows required by inline
bindings. Callers remain responsible for deciding whether to save the returned
graph.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from models.agent_config_entities import (
    AgentSoulDifyToolConfig,
    AgentSoulModelConfig,
    AgentSoulModelSettings,
    AgentSoulToolsConfig,
)
from models.provider_ids import ModelProviderID
from services.agent.composer_service import AgentComposerService
from services.entities.agent_entities import AgentSoulConfig


def _agent_soul_from_node_data(data: dict[str, Any]) -> AgentSoulConfig | None:
    model = data.get("model")
    if not isinstance(model, dict):
        return None

    provider = model.get("provider")
    model_name = model.get("name")
    if not isinstance(provider, str) or not provider.strip():
        return None
    if not isinstance(model_name, str) or not model_name.strip():
        return None

    try:
        provider_id = ModelProviderID(provider.strip())
        settings = AgentSoulModelSettings.model_validate(model.get("completion_params") or {})
    except (TypeError, ValueError):
        return None

    return AgentSoulConfig(
        model=AgentSoulModelConfig(
            plugin_id=provider_id.plugin_id,
            model_provider=provider.strip(),
            model=model_name.strip(),
            model_settings=settings,
        ),
        tools=_dify_tools_from_node_data(data),
    )


def _dify_tools_from_node_data(data: dict[str, Any]) -> AgentSoulToolsConfig:
    raw_tools = data.get("dify_tools")
    if not isinstance(raw_tools, list):
        return AgentSoulToolsConfig()
    parsed: list[AgentSoulDifyToolConfig] = []
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        try:
            payload = dict(item)
            if "credential_type" not in payload:
                payload["credential_type"] = "unauthorized"
            parsed.append(AgentSoulDifyToolConfig.model_validate(payload))
        except (TypeError, ValueError):
            continue
    return AgentSoulToolsConfig(dify_tools=parsed)


def create_inline_binding_for_node(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    node_id: str,
    account_id: str,
    agent_soul: AgentSoulConfig | None = None,
) -> tuple[str, str]:
    """Create an inline Agent v2 binding and return its agent and snapshot ids.

    The helper intentionally creates only Agent-related rows through the
    composer service; it never writes workflow draft graph JSON.
    """
    agent = AgentComposerService._create_workflow_only_agent(
        session=session,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=workflow_id,
        node_id=node_id,
        account_id=account_id,
        agent_soul=agent_soul or AgentSoulConfig(),
    )
    return str(agent.id), str(agent.active_config_snapshot_id)


def hydrate_agent_bindings(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    account_id: str,
    workflow_id: str,
    graph: dict[str, Any],
) -> dict[str, Any]:
    """Return a copied graph with missing inline Agent v2 bindings created.

    Existing complete inline bindings are retained. This function creates Agent
    and snapshot rows but does not write workflow draft graph JSON.
    """
    hydrated_graph = copy.deepcopy(graph)
    for node in hydrated_graph.get("nodes", []):
        data = node.get("data") or {}
        if data.get("type") != "agent" or str(data.get("version")) != "2":
            continue

        binding = data.get("agent_binding") or {"binding_type": "inline_agent"}
        if binding.get("binding_type") != "inline_agent":
            continue

        agent_id = binding.get("agent_id")
        snapshot_id = binding.get("current_snapshot_id")
        if isinstance(agent_id, str) and agent_id and isinstance(snapshot_id, str) and snapshot_id:
            continue

        agent_id, snapshot_id = create_inline_binding_for_node(
            session=session,
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_id=workflow_id,
            node_id=node["id"],
            account_id=account_id,
            agent_soul=_agent_soul_from_node_data(data),
        )
        data["agent_binding"] = {
            "binding_type": "inline_agent",
            "agent_id": agent_id,
            "current_snapshot_id": snapshot_id,
        }
        data["agent_node_kind"] = "dify_agent"
        data["version"] = "2"
        node["data"] = data

    return hydrated_graph
