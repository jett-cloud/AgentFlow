"""Hydrate generated Agent v2 nodes without persisting workflow draft graphs.

This module prepares backing Agent and immutable snapshot rows for candidates.
It never updates draft bindings or an existing Agent's active snapshot. Callers decide whether
to save the returned graph. Binding ids on the graph are trusted only after a
database ownership check; forged or stale ids are recreated rather than skipped.

``assist_binding_manifest`` is a declaration of intended Tool/MCP/dataset keys,
not an authorization token. Live tenant catalogues are re-checked before any
row is written. The idempotent key is the workflow node id (or a trusted
``agent_id`` already owned by that node).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.workflow.generator.compiler.agent_knowledge import collect_agent_knowledge_dataset_ids
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry, installed_tool_keys
from core.workflow.generator.types import WorkflowGenerateErrorCode, WorkflowGenerateErrorDict
from core.workflow.generator.validation.agent_config import collect_unhydrated_inline_agent_errors
from models.agent import (
    Agent,
    AgentConfigRevisionOperation,
    AgentConfigSnapshot,
    AgentScope,
    AgentStatus,
    WorkflowAgentBindingType,
    WorkflowAgentNodeBinding,
)
from models.agent_config_entities import (
    AgentSoulConfig,
    AgentSoulDifyToolConfig,
    AgentSoulKnowledgeConfig,
    AgentSoulModelConfig,
    AgentSoulModelSettings,
    AgentSoulToolsConfig,
    DeclaredOutputConfig,
    WorkflowNodeJobConfig,
)
from models.provider_ids import ModelProviderID
from models.workflow import Workflow
from services.agent.agent_soul_state import agent_soul_has_model
from services.agent.composer_service import AgentComposerService
from services.agent.errors import InvalidComposerConfigError
from services.workflow_assist.knowledge_catalogue_loader import build_knowledge_catalogue
from services.workflow_assist.tool_catalogue_loader import build_tool_catalogue


@dataclass(frozen=True)
class TrustedInlineBinding:
    """Verified Agent + snapshot owned by this tenant/app/workflow/node."""

    agent: Agent
    snapshot: AgentConfigSnapshot


class AgentBindingHydrationError(ValueError):
    """Recoverable hydrate failure. Does not fill binding ids or record Evidence."""

    code: str
    detail: str
    node_id: str

    def __init__(self, code: str, detail: str, *, node_id: str = "") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.node_id = node_id


class InvalidAgentSoulProjectionError(AgentBindingHydrationError):
    """Raised before persistence when an Agent node cannot produce a valid Soul."""

    def __init__(self, detail: str, *, node_id: str = "") -> None:
        super().__init__("INVALID_AGENT_NODE", detail, node_id=node_id)


def _agent_soul_from_node_data(
    data: dict[str, Any],
    *,
    base_soul: AgentSoulConfig | None = None,
) -> AgentSoulConfig | None:
    """Overlay projected node fields onto a trusted complete Soul."""
    soul = copy.deepcopy(base_soul) if base_soul is not None else AgentSoulConfig()
    if "model" in data:
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
        soul.model = AgentSoulModelConfig(
            plugin_id=provider_id.plugin_id,
            model_provider=provider.strip(),
            model=model_name.strip(),
            model_settings=settings,
        )
    elif base_soul is None:
        return None

    if "dify_tools" in data:
        soul.tools = _dify_tools_from_node_data(data)
    if "knowledge" in data:
        try:
            soul.knowledge = AgentSoulKnowledgeConfig.model_validate(data.get("knowledge"))
        except (TypeError, ValueError, ValidationError):
            return None
    return soul


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
        except (TypeError, ValueError, ValidationError):
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
    """Return a copied graph with trusted inline Agent v2 bindings.

    Missing or untrusted ``agent_id`` / ``current_snapshot_id`` values reuse an
    owned workflow-only Agent for the node when one exists; otherwise a new
    Agent is created. Trusted ids keep the same Agent; model/tool/knowledge
    Soul changes write a new snapshot on that Agent. Invalid projected
    knowledge or live catalogue misses raise before any Agent row is created
    or refreshed. Acceptance uses a candidate resolver; only Apply may update
    draft bindings.
    """
    hydrated_graph = copy.deepcopy(graph)
    pending: list[tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]] = []
    for node in hydrated_graph.get("nodes", []):
        data = node.get("data") or {}
        if data.get("type") != "agent" or str(data.get("version")) != "2":
            continue
        binding = data.get("agent_binding") or {"binding_type": "inline_agent"}
        if binding.get("binding_type") != "inline_agent":
            continue
        pending.append((node, data, str(node["id"]), binding))

    tool_entries = _live_tool_entries(tenant_id, pending)
    dataset_ids = _live_dataset_ids(tenant_id, pending)
    prepared: list[tuple[dict[str, Any], dict[str, Any], str, TrustedInlineBinding | None, AgentSoulConfig | None]] = []
    for node, data, node_id, binding in pending:
        if _assist_binding_manifest(data) is not None:
            _assert_live_membership(data, node_id=node_id, tool_entries=tool_entries, dataset_ids=dataset_ids)
        trusted = _resolve_owned_inline_binding(
            session=session,
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_id=workflow_id,
            node_id=node_id,
            agent_id=binding.get("agent_id"),
            snapshot_id=binding.get("current_snapshot_id"),
        )
        base_soul = _snapshot_agent_soul(trusted.snapshot) if trusted is not None else None
        soul = _agent_soul_from_node_data(data, base_soul=base_soul)
        if soul is None and "knowledge" in data:
            raise InvalidAgentSoulProjectionError(
                f"invalid Agent Soul projection for node {node_id!r}",
                node_id=node_id,
            )
        if soul is not None and _assist_binding_manifest(data) is not None:
            try:
                AgentComposerService.validate_knowledge_datasets(
                    session=session,
                    tenant_id=tenant_id,
                    agent_soul=soul,
                )
            except InvalidComposerConfigError as exc:
                raise AgentBindingHydrationError(
                    WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                    f"Agent node {node_id!r} references a missing or out-of-scope knowledge dataset",
                    node_id=node_id,
                ) from exc
        prepared.append((node, data, node_id, trusted, soul))

    try:
        _persist_prepared_bindings(
            session=session,
            tenant_id=tenant_id,
            app_id=app_id,
            account_id=account_id,
            workflow_id=workflow_id,
            prepared=prepared,
        )
        session.flush()
    except AgentBindingHydrationError:
        raise
    except Exception as exc:
        raise AgentBindingHydrationError(
            WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            "Failed to persist Agent binding",
        ) from exc
    return hydrated_graph


def collect_invalid_inline_agent_binding_errors(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    nodes: list[dict[str, Any]],
) -> list[WorkflowGenerateErrorDict]:
    """Return missing-id and untrusted-ownership errors for inline Agent nodes.

    Apply uses this after hydrate should already have run. Invalid ids are
    ``INVALID_AGENT_NODE`` rather than a 500 during later binding sync.
    """
    errors = collect_unhydrated_inline_agent_errors(nodes)
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != "agent":
            continue
        binding = data.get("agent_binding")
        if not isinstance(binding, dict) or binding.get("binding_type") != "inline_agent":
            continue
        agent_id = binding.get("agent_id")
        snapshot_id = binding.get("current_snapshot_id")
        if not (
            isinstance(agent_id, str) and agent_id.strip() and isinstance(snapshot_id, str) and snapshot_id.strip()
        ):
            continue
        node_id = str(node.get("id") or "")
        trusted = _load_trusted_inline_binding(
            session=session,
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_id=workflow_id,
            node_id=node_id,
            agent_id=agent_id,
            snapshot_id=snapshot_id,
        )
        if trusted is not None and candidate_soul_matches_snapshot(data, trusted.snapshot):
            agent_soul = _snapshot_agent_soul(trusted.snapshot)
            try:
                AgentComposerService.validate_knowledge_datasets(
                    session=session,
                    tenant_id=tenant_id,
                    agent_soul=agent_soul,
                )
            except InvalidComposerConfigError:
                errors.append(
                    {
                        "code": WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                        "detail": (f"Agent node {node_id!r} references a missing or out-of-scope knowledge dataset"),
                        "node_id": node_id,
                    }
                )
            continue
        errors.append(
            {
                "code": WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
                "detail": (
                    f"Agent node {node_id!r} inline binding does not belong to this "
                    "workflow node or its snapshot does not match the candidate configuration"
                ),
                "node_id": node_id,
            }
        )
    return errors


def candidate_soul_matches_snapshot(data: dict[str, Any], snapshot: AgentConfigSnapshot) -> bool:
    """A valid owner is insufficient if the candidate changed after hydration."""
    base_soul = _snapshot_agent_soul(snapshot)
    if base_soul is None:
        return False
    soul = _agent_soul_from_node_data(data, base_soul=base_soul)
    return soul is not None and soul.model_dump(mode="json") == base_soul.model_dump(mode="json")


def _assist_binding_manifest(data: dict[str, Any]) -> dict[str, Any] | None:
    raw = data.get("assist_binding_manifest")
    return raw if isinstance(raw, dict) else None


def _declared_tool_keys(data: dict[str, Any]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    manifest = _assist_binding_manifest(data)
    raw_keys = manifest.get("tool_keys") if manifest is not None else None
    if isinstance(raw_keys, list):
        for item in raw_keys:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            key = (str(item[0]), str(item[1]))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    for item in data.get("dify_tools") or []:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider_id")
        tool_name = item.get("tool_name")
        if not isinstance(provider, str) or not isinstance(tool_name, str):
            continue
        key = (provider, tool_name)
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _declared_dataset_ids(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    manifest = _assist_binding_manifest(data)
    raw_ids = manifest.get("dataset_ids") if manifest is not None else None
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if not isinstance(item, str) or not item.strip() or item in seen:
                continue
            seen.add(item)
            ids.append(item)
    for dataset_id in collect_agent_knowledge_dataset_ids(data):
        if dataset_id in seen:
            continue
        seen.add(dataset_id)
        ids.append(dataset_id)
    return ids


def _pending_needs_tools(pending: list[tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]]) -> bool:
    return any(_assist_binding_manifest(data) is not None and _declared_tool_keys(data) for _, data, _, _ in pending)


def _pending_needs_datasets(pending: list[tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]]) -> bool:
    return any(_assist_binding_manifest(data) is not None and _declared_dataset_ids(data) for _, data, _, _ in pending)


def _live_tool_entries(
    tenant_id: str,
    pending: list[tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]],
) -> list[ToolCatalogueEntry]:
    if not _pending_needs_tools(pending):
        return []
    return build_tool_catalogue(tenant_id, limit=None, raise_on_error=True)


def _live_dataset_ids(
    tenant_id: str,
    pending: list[tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]],
) -> set[str]:
    if not _pending_needs_datasets(pending):
        return set()
    return {entry["id"] for entry in build_knowledge_catalogue(tenant_id, limit=None, raise_on_error=True)}


def _assert_live_membership(
    data: dict[str, Any],
    *,
    node_id: str,
    tool_entries: list[ToolCatalogueEntry],
    dataset_ids: set[str],
) -> None:
    installed_tools = installed_tool_keys(tool_entries)
    for provider_name, tool_name in _declared_tool_keys(data):
        if (provider_name, tool_name) not in installed_tools:
            raise AgentBindingHydrationError(
                WorkflowGenerateErrorCode.UNKNOWN_TOOL,
                f"Tool {provider_name}/{tool_name} is not present in the current catalogue",
                node_id=node_id,
            )
    live_datasets = dataset_ids
    for dataset_id in _declared_dataset_ids(data):
        if dataset_id not in live_datasets:
            raise AgentBindingHydrationError(
                WorkflowGenerateErrorCode.UNKNOWN_DATASET,
                f"Agent node {node_id!r} references a missing or out-of-scope knowledge dataset",
                node_id=node_id,
            )


def _persist_prepared_bindings(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    account_id: str,
    workflow_id: str,
    prepared: list[tuple[dict[str, Any], dict[str, Any], str, TrustedInlineBinding | None, AgentSoulConfig | None]],
) -> None:
    for node, data, node_id, trusted, soul in prepared:
        if trusted is None:
            agent_id, snapshot_id = create_inline_binding_for_node(
                session=session,
                tenant_id=tenant_id,
                app_id=app_id,
                workflow_id=workflow_id,
                node_id=node_id,
                account_id=account_id,
                agent_soul=soul,
            )
        else:
            agent_id = str(trusted.agent.id)
            snapshot_id = _refresh_inline_soul(
                session=session,
                trusted=trusted,
                account_id=account_id,
                agent_soul=soul,
            )
        data["agent_binding"] = {
            "binding_type": "inline_agent",
            "agent_id": agent_id,
            "current_snapshot_id": snapshot_id,
        }
        data["agent_node_kind"] = "dify_agent"
        data["version"] = "2"
        node["data"] = data


def _resolve_owned_inline_binding(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    node_id: str,
    agent_id: object,
    snapshot_id: object,
) -> TrustedInlineBinding | None:
    trusted = _load_trusted_inline_binding(
        session=session,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=workflow_id,
        node_id=node_id,
        agent_id=agent_id,
        snapshot_id=snapshot_id,
    )
    if trusted is not None:
        return trusted
    return _load_owned_inline_agent_for_node(
        session=session,
        tenant_id=tenant_id,
        app_id=app_id,
        workflow_id=workflow_id,
        node_id=node_id,
        snapshot_id=snapshot_id,
    )


def _snapshot_agent_soul(snapshot: AgentConfigSnapshot) -> AgentSoulConfig | None:
    raw = snapshot.config_snapshot
    if isinstance(raw, AgentSoulConfig):
        return raw
    try:
        return AgentSoulConfig.model_validate(raw)
    except (TypeError, ValueError, ValidationError):
        return None


def _load_trusted_inline_binding(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    node_id: str,
    agent_id: object,
    snapshot_id: object,
) -> TrustedInlineBinding | None:
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        return None
    agent = session.scalar(
        select(Agent)
        .where(
            Agent.tenant_id == tenant_id,
            Agent.id == agent_id,
            Agent.scope == AgentScope.WORKFLOW_ONLY,
            Agent.app_id == app_id,
            Agent.workflow_id == workflow_id,
            Agent.workflow_node_id == node_id,
            Agent.status == AgentStatus.ACTIVE,
        )
        .limit(1)
    )
    if not isinstance(agent, Agent):
        return None
    snapshot = session.scalar(
        select(AgentConfigSnapshot)
        .where(
            AgentConfigSnapshot.tenant_id == tenant_id,
            AgentConfigSnapshot.agent_id == agent.id,
            AgentConfigSnapshot.id == snapshot_id,
        )
        .limit(1)
    )
    if not isinstance(snapshot, AgentConfigSnapshot) or snapshot.agent_id != agent.id:
        return None
    return TrustedInlineBinding(agent=agent, snapshot=snapshot)


def _load_owned_inline_agent_for_node(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    node_id: str,
    snapshot_id: object,
) -> TrustedInlineBinding | None:
    agent = session.scalar(
        select(Agent)
        .where(
            Agent.tenant_id == tenant_id,
            Agent.app_id == app_id,
            Agent.workflow_id == workflow_id,
            Agent.workflow_node_id == node_id,
            Agent.scope == AgentScope.WORKFLOW_ONLY,
            Agent.status == AgentStatus.ACTIVE,
        )
        .limit(1)
    )
    if not isinstance(agent, Agent):
        return None
    if isinstance(snapshot_id, str) and snapshot_id.strip():
        snapshot = session.scalar(
            select(AgentConfigSnapshot)
            .where(
                AgentConfigSnapshot.tenant_id == tenant_id,
                AgentConfigSnapshot.agent_id == agent.id,
                AgentConfigSnapshot.id == snapshot_id,
            )
            .limit(1)
        )
        if isinstance(snapshot, AgentConfigSnapshot):
            return TrustedInlineBinding(agent=agent, snapshot=snapshot)
    snapshot = session.scalar(
        select(AgentConfigSnapshot)
        .where(
            AgentConfigSnapshot.tenant_id == tenant_id,
            AgentConfigSnapshot.agent_id == agent.id,
        )
        .order_by(AgentConfigSnapshot.version.desc())
        .limit(1)
    )
    if not isinstance(snapshot, AgentConfigSnapshot):
        return None
    return TrustedInlineBinding(agent=agent, snapshot=snapshot)


def _refresh_inline_soul(
    *,
    session: Session,
    trusted: TrustedInlineBinding,
    account_id: str,
    agent_soul: AgentSoulConfig | None,
) -> str:
    """Write a new snapshot when Soul config changed; keep the same Agent."""
    if agent_soul is None:
        return str(trusted.snapshot.id)
    current_payload = (
        trusted.snapshot.config_snapshot.model_dump(mode="json")
        if hasattr(trusted.snapshot.config_snapshot, "model_dump")
        else trusted.snapshot.config_snapshot_dict
    )
    if agent_soul.model_dump(mode="json") == current_payload:
        return str(trusted.snapshot.id)
    # Serialize version allocation for concurrent candidates of the same Agent.
    session.scalar(
        select(Agent).where(Agent.id == trusted.agent.id, Agent.tenant_id == trusted.agent.tenant_id).with_for_update()
    )
    version = AgentComposerService._create_config_version(
        session=session,
        tenant_id=trusted.agent.tenant_id,
        agent_id=trusted.agent.id,
        account_id=account_id,
        agent_soul=agent_soul,
        operation=AgentConfigRevisionOperation.SAVE_CURRENT_VERSION,
        version_note=None,
        previous_snapshot_id=trusted.snapshot.id,
    )
    return str(version.id)


def activate_candidate_bindings(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    account_id: str,
    nodes: list[dict[str, Any]],
) -> None:
    """Activate verified candidate bindings inside the Apply transaction only."""
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != "agent":
            continue
        binding = data["agent_binding"]
        trusted = _load_trusted_inline_binding(
            session=session,
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_id=workflow_id,
            node_id=node["id"],
            agent_id=binding["agent_id"],
            snapshot_id=binding["current_snapshot_id"],
        )
        if trusted is None or not candidate_soul_matches_snapshot(data, trusted.snapshot):
            raise ValueError(f"Candidate Agent binding unavailable for {node['id']}")
        trusted.agent.active_config_snapshot_id = trusted.snapshot.id
        trusted.agent.active_config_has_model = agent_soul_has_model(trusted.snapshot.config_snapshot)
        trusted.agent.updated_by = account_id
        _ensure_inline_binding(
            session=session,
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_id=workflow_id,
            node_id=node["id"],
            account_id=account_id,
            agent_id=trusted.agent.id,
            snapshot_id=trusted.snapshot.id,
            data=data,
        )


def _ensure_inline_binding(
    *,
    session: Session,
    tenant_id: str,
    app_id: str,
    workflow_id: str,
    node_id: str,
    account_id: str,
    agent_id: str,
    snapshot_id: str,
    data: dict[str, Any],
) -> None:
    existing = session.scalar(
        select(WorkflowAgentNodeBinding)
        .where(
            WorkflowAgentNodeBinding.tenant_id == tenant_id,
            WorkflowAgentNodeBinding.app_id == app_id,
            WorkflowAgentNodeBinding.workflow_id == workflow_id,
            WorkflowAgentNodeBinding.workflow_version == Workflow.VERSION_DRAFT,
            WorkflowAgentNodeBinding.node_id == node_id,
        )
        .limit(1)
    )
    node_job = _node_job_from_data(data)
    if isinstance(existing, WorkflowAgentNodeBinding):
        existing.binding_type = WorkflowAgentBindingType.INLINE_AGENT
        existing.agent_id = agent_id
        existing.current_snapshot_id = snapshot_id
        existing.node_job_config = node_job
        existing.updated_by = account_id
        return
    session.add(
        WorkflowAgentNodeBinding(
            tenant_id=tenant_id,
            app_id=app_id,
            workflow_id=workflow_id,
            workflow_version=Workflow.VERSION_DRAFT,
            node_id=node_id,
            binding_type=WorkflowAgentBindingType.INLINE_AGENT,
            agent_id=agent_id,
            current_snapshot_id=snapshot_id,
            node_job_config=node_job,
            created_by=account_id,
            updated_by=account_id,
        )
    )


def _node_job_from_data(data: dict[str, Any]) -> WorkflowNodeJobConfig:
    node_job = WorkflowNodeJobConfig()
    agent_task = data.get("agent_task")
    if isinstance(agent_task, str):
        node_job.workflow_prompt = agent_task
    declared = data.get("agent_declared_outputs")
    if not isinstance(declared, list):
        return node_job
    parsed: list[DeclaredOutputConfig] = []
    for item in declared:
        try:
            parsed.append(DeclaredOutputConfig.model_validate(item))
        except ValidationError:
            continue
    node_job.declared_outputs = parsed
    return node_job
