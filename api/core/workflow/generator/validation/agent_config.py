"""agent config."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from core.workflow.generator.types import WorkflowGenerateErrorCode, WorkflowGenerateErrorDict
from core.workflow.generator.validation.node_validation_values import _err, _non_empty_string, _pydantic_config_errors
from graphon.enums import BuiltinNodeTypes
from models.agent_config_entities import (
    AgentSoulDifyToolConfig,
    AgentSoulKnowledgeConfig,
    AgentSoulModelSettings,
    DeclaredOutputConfig,
)


def collect_unhydrated_inline_agent_errors(nodes: list[dict[str, Any]]) -> list[WorkflowGenerateErrorDict]:
    """Return errors for inline Agent v2 nodes that still lack binding ids.

    This is a string-presence check only. Ownership of those ids is verified in
    ``services.workflow_assist.hydrate``. Pre-hydrate ``validate_graph`` must not
    call this. Finish, Apply, and ``run_acceptance`` use it after hydrate.
    """
    errors: list[WorkflowGenerateErrorDict] = []
    for node in nodes:
        data = node.get("data") or {}
        if data.get("type") != BuiltinNodeTypes.AGENT:
            continue
        binding = data.get("agent_binding")
        if not isinstance(binding, dict) or binding.get("binding_type") != "inline_agent":
            continue
        node_id = str(node.get("id") or "")
        if _non_empty_string(binding.get("agent_id")) and _non_empty_string(binding.get("current_snapshot_id")):
            continue
        errors.append(
            _err(
                f"Agent node {node_id!r} inline binding is missing agent_id and current_snapshot_id",
                node_id,
                WorkflowGenerateErrorCode.AGENT_BINDING_MISSING,
            )
        )
    return errors


def _agent_node_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    errors: list[WorkflowGenerateErrorDict] = []
    if str(data.get("version")) != "2" or data.get("agent_node_kind") != "dify_agent":
        errors.append(
            _err(
                f"Agent node {node_id!r} must use version='2' and agent_node_kind='dify_agent'",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        )
    if not _non_empty_string(data.get("agent_task")):
        errors.append(
            _err(
                f"Agent node {node_id!r} has empty agent_task",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        )
    errors.extend(_agent_model_errors(node_id=node_id, data=data))
    errors.extend(_agent_declared_output_errors(node_id=node_id, data=data))
    errors.extend(_agent_binding_type_errors(node_id=node_id, data=data))
    errors.extend(_agent_dify_tools_shape_errors(node_id=node_id, data=data))
    errors.extend(_agent_knowledge_shape_errors(node_id=node_id, data=data))
    return errors


def _agent_model_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    model = data.get("model")
    if not isinstance(model, dict):
        return [
            _err(
                f"Agent node {node_id!r} has invalid model config",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        ]
    provider = model.get("provider")
    name = model.get("name")
    if not _non_empty_string(provider) or not _non_empty_string(name):
        return [
            _err(
                f"Agent node {node_id!r} model requires non-empty provider and name",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        ]
    try:
        settings = model.get("completion_params")
        AgentSoulModelSettings.model_validate({} if settings is None else settings)
    except ValidationError as exc:
        return _pydantic_config_errors(node_id=node_id, prefix="model.completion_params", exc=exc)
    return []


def _agent_declared_output_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    declared = data.get("agent_declared_outputs")
    if declared is None:
        return []
    if not isinstance(declared, list):
        return [
            _err(
                f"Agent node {node_id!r} agent_declared_outputs must be a list",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        ]
    errors: list[WorkflowGenerateErrorDict] = []
    seen_names: set[str] = set()
    for index, item in enumerate(declared):
        try:
            parsed = DeclaredOutputConfig.model_validate(item)
        except ValidationError as exc:
            errors.extend(
                _pydantic_config_errors(
                    node_id=node_id,
                    prefix=f"agent_declared_outputs[{index}]",
                    exc=exc,
                )
            )
            continue
        if parsed.name in seen_names:
            errors.append(
                _err(
                    f"Agent node {node_id!r} agent_declared_outputs has duplicate name {parsed.name!r}",
                    node_id,
                    WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
                )
            )
            continue
        seen_names.add(parsed.name)
    return errors


def _agent_binding_type_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    binding = data.get("agent_binding")
    if isinstance(binding, dict) and binding.get("binding_type") == "inline_agent":
        return []
    return [
        _err(
            f"Agent node {node_id!r} requires agent_binding.binding_type='inline_agent'",
            node_id,
            WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
        )
    ]


def _agent_dify_tools_shape_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    dify_tools = data.get("dify_tools")
    if dify_tools is None:
        return []
    if not isinstance(dify_tools, list):
        return [
            _err(
                f"Agent node {node_id!r} dify_tools must be a list",
                node_id,
                WorkflowGenerateErrorCode.INVALID_AGENT_NODE,
            )
        ]
    errors: list[WorkflowGenerateErrorDict] = []
    for index, item in enumerate(dify_tools):
        payload: object = item
        if isinstance(item, dict) and "credential_type" not in item:
            payload = {**item, "credential_type": "unauthorized"}
        try:
            AgentSoulDifyToolConfig.model_validate(payload)
        except ValidationError as exc:
            errors.extend(
                _pydantic_config_errors(
                    node_id=node_id,
                    prefix=f"dify_tools[{index}]",
                    exc=exc,
                )
            )
    return errors


def _agent_knowledge_shape_errors(*, node_id: str, data: dict[str, Any]) -> list[WorkflowGenerateErrorDict]:
    if "knowledge" not in data:
        return []
    try:
        AgentSoulKnowledgeConfig.model_validate(data.get("knowledge"))
    except ValidationError as exc:
        return _pydantic_config_errors(node_id=node_id, prefix="knowledge", exc=exc)
    return []
