"""Versioned Workflow Assist plan contract and deterministic submit reducer.

The contract is authoritative conversation state, separate from prompt
compaction and graph revision. The model proposes a complete replacement with
an expected revision; this module validates user-turn evidence, edit scope,
and requirement continuity, then computes the canonical hash. It is pure
domain code and performs no persistence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.workflow.generator.agent.tools.tool_context import ToolContext
from core.workflow.generator.agent.tools.tool_results import error, ok
from core.workflow.generator.agent.types import ToolCall, ToolResult
from core.workflow.generator.contracts.requirement_evidence import (
    evidence_occurs_in_turn,
    normalize_requirement_evidence,
)
from core.workflow.generator.graph.graph_ops import find_node

WORKFLOW_CONTRACT_PROTOCOL_VERSION: Literal[1] = 1
WORKFLOW_CONTRACT_SCHEMA_VERSION = 1
_GRAPH_MUTATION_TOOLS = frozenset(
    {
        "build_node",
        "build_tool_node",
        "build_agent_node",
        "build_loop",
        "build_iteration",
        "delete_node",
        "connect",
        "disconnect",
    }
)
_NODE_BUILD_TOOLS = frozenset({"build_node", "build_tool_node", "build_agent_node", "build_loop", "build_iteration"})


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowRequirement(_ContractModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    source_turn_id: str = Field(min_length=1, max_length=128)
    evidence: str = Field(min_length=1, max_length=2_000)
    text: str = Field(min_length=1, max_length=2_000)
    provenance: Literal["explicit_user", "model_interpretation"]
    supersedes: list[str] = Field(default_factory=list, max_length=32)


class WorkflowEditScope(_ContractModel):
    candidate_base_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_node_ids: list[str] = Field(min_length=1, max_length=200)
    affected_downstream_ids: list[str] = Field(default_factory=list, max_length=200)


class WorkflowPlanInput(_ContractModel):
    source: tuple[str, ...] = Field(min_length=2, max_length=12)
    role: str = Field(min_length=1, max_length=128)


class WorkflowPlanNodeOutput(_ContractModel):
    name: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=64)


class WorkflowPlanNode(_ContractModel):
    id: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    type: str = Field(min_length=1, max_length=64)
    objective: str = Field(min_length=1, max_length=2_000)
    requirement_ids: list[str] = Field(default_factory=list, max_length=64)
    inputs: list[WorkflowPlanInput] = Field(default_factory=list, max_length=100)
    outputs: list[WorkflowPlanNodeOutput] = Field(default_factory=list, max_length=100)
    structure_kind: str | None = Field(default=None, max_length=64)
    unresolved: list[str] = Field(default_factory=list, max_length=32)


class WorkflowPlanEdge(_ContractModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    source_handle: str | None = Field(default=None, max_length=128)


class WorkflowPlanOutput(_ContractModel):
    name: str = Field(min_length=1, max_length=128)
    source: tuple[str, ...] = Field(min_length=2, max_length=12)
    type: str = Field(min_length=1, max_length=64)


class WorkflowDatasetResource(_ContractModel):
    kind: Literal["dataset"]
    dataset_id: str = Field(min_length=1, max_length=255)
    consumer_id: str = Field(min_length=1, max_length=50)


class WorkflowToolResource(_ContractModel):
    kind: Literal["tool"]
    provider_name: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=255)
    consumer_id: str = Field(min_length=1, max_length=50)


class WorkflowModelResource(_ContractModel):
    kind: Literal["model"]
    provider: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    mode: str = Field(min_length=1, max_length=64)
    consumer_id: str = Field(min_length=1, max_length=50)


WorkflowResource = Annotated[
    WorkflowDatasetResource | WorkflowToolResource | WorkflowModelResource,
    Field(discriminator="kind"),
]


class _ResolvedResource(_ContractModel):
    verified: bool
    unresolved_reason: Literal["catalogue_unavailable", "not_found"] | None = None


class ResolvedDatasetResource(WorkflowDatasetResource, _ResolvedResource):
    pass


class ResolvedToolResource(WorkflowToolResource, _ResolvedResource):
    pass


class ResolvedModelResource(WorkflowModelResource, _ResolvedResource):
    pass


ResolvedWorkflowResource = Annotated[
    ResolvedDatasetResource | ResolvedToolResource | ResolvedModelResource,
    Field(discriminator="kind"),
]


class WorkflowPlanCheck(_ContractModel):
    id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_000)
    level: Literal["static", "simulated", "live", "business"]
    requirement_ids: list[str] = Field(default_factory=list, max_length=64)


class WorkflowPlan(_ContractModel):
    schema_version: Literal[1]
    status: Literal["draft", "complete"]
    operation: Literal["rebuild", "edit"]
    requirements: list[WorkflowRequirement] = Field(max_length=200)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    edit_scope: WorkflowEditScope | None
    nodes: list[WorkflowPlanNode] = Field(max_length=200)
    edges: list[WorkflowPlanEdge] = Field(default_factory=list, max_length=400)
    final_outputs: list[WorkflowPlanOutput] = Field(default_factory=list, max_length=100)
    resources: list[WorkflowResource] = Field(default_factory=list, max_length=200)
    checks: list[WorkflowPlanCheck] = Field(default_factory=list, max_length=200)
    unresolved: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_internal_references(self) -> WorkflowPlan:
        requirement_ids = [item.id for item in self.requirements]
        node_ids = [item.id for item in self.nodes]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("requirement ids must be unique")
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node ids must be unique")
        requirement_set = set(requirement_ids)
        node_set = set(node_ids)
        for node in self.nodes:
            if not set(node.requirement_ids).issubset(requirement_set):
                raise ValueError(f"node {node.id!r} references an unknown requirement")
        for edge in self.edges:
            if edge.source not in node_set or edge.target not in node_set:
                raise ValueError("control edge references an unknown plan node")
        for output in self.final_outputs:
            if output.source[0] not in node_set:
                raise ValueError(f"final output {output.name!r} references an unknown plan node")
        for resource in self.resources:
            if resource.consumer_id not in node_set:
                raise ValueError("resource binding references an unknown consumer")
        for check in self.checks:
            if not set(check.requirement_ids).issubset(requirement_set):
                raise ValueError(f"check {check.id!r} references an unknown requirement")
        if self.operation == "edit" and self.edit_scope is None:
            raise ValueError("edit operation requires edit_scope")
        if self.operation == "rebuild" and self.edit_scope is not None:
            raise ValueError("rebuild operation must not include edit_scope")
        if self.status == "complete":
            if self.unresolved or any(node.unresolved for node in self.nodes):
                raise ValueError("complete plan cannot contain unresolved items")
            if not self.requirements or not self.nodes or not self.final_outputs or not self.checks:
                raise ValueError("complete plan requires requirements, nodes, final_outputs, and checks")
            node_requirement_ids = {requirement_id for node in self.nodes for requirement_id in node.requirement_ids}
            check_requirement_ids = {
                requirement_id for check in self.checks for requirement_id in check.requirement_ids
            }
            uncovered = requirement_set - (node_requirement_ids & check_requirement_ids)
            if uncovered:
                raise ValueError(
                    f"requirements must be referenced by at least one node and check: {sorted(uncovered)!r}"
                )
        return self


class WorkflowContract(WorkflowPlan):
    resources: list[ResolvedWorkflowResource] = Field(default_factory=list, max_length=200)
    protocol_version: Literal[1]
    revision: int = Field(ge=1)
    contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_contract_has_verified_resources(self) -> Self:
        if self.status == "complete" and any(not resource.verified for resource in self.resources):
            raise ValueError("complete contract cannot contain unverified resources")
        return self


def submit_workflow_plan(call: ToolCall, context: ToolContext) -> ToolResult:
    """Validate and replace the plan without mutating graph revision."""
    if context.state.contract_protocol_version != WORKFLOW_CONTRACT_PROTOCOL_VERSION:
        return error(call, "CONTRACT_PROTOCOL_UNAVAILABLE", "This run does not use the workflow contract protocol")
    expected_revision = call["arguments"].get("expected_revision")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        return error(call, "INVALID_ARGUMENT", "expected_revision must be a non-negative integer")
    current_revision = context.state.contract_revision
    if expected_revision != current_revision:
        return error(
            call,
            "CONTRACT_REVISION_CONFLICT",
            f"Expected contract revision {expected_revision}, current revision is {current_revision}",
            cause={"expected_revision": expected_revision, "current_revision": current_revision},
        )
    raw_plan = call["arguments"].get("plan")
    try:
        plan = WorkflowPlan.model_validate(raw_plan)
    except ValidationError as exc:
        first = exc.errors(include_input=False)[0]
        path = ".".join(str(part) for part in first.get("loc", ()))
        return error(call, "INVALID_WORKFLOW_PLAN", str(first.get("msg") or "invalid plan"), path=path or "plan")
    if plan.operation == "edit" and context.env.contract_rollout_stage not in {"local_edits", "default"}:
        return error(
            call,
            "CONTRACT_EDIT_ROLLOUT_DISABLED",
            "Edit workflow contracts are not enabled for this rollout stage",
        )
    unknown_turns = sorted(
        {
            requirement.source_turn_id
            for requirement in plan.requirements
            if requirement.source_turn_id not in context.state.user_turn_evidence
        }
    )

    if unknown_turns:
        return error(
            call,
            "UNKNOWN_REQUIREMENT_TURN",
            "Plan requirements must reference durable user turns",
            cause={"source_turn_ids": unknown_turns},
        )
    invalid_evidence = sorted(
        requirement.id
        for requirement in plan.requirements
        if requirement.provenance == "explicit_user"
        and not evidence_occurs_in_turn(
            evidence=requirement.evidence,
            user_text=context.state.user_turn_evidence[requirement.source_turn_id],
        )
    )
    if invalid_evidence:
        return error(
            call,
            "INVALID_REQUIREMENT_EVIDENCE",
            "Explicit requirements must quote evidence from their durable user turn",
            cause={"requirement_ids": invalid_evidence},
        )
    if plan.edit_scope is not None and plan.edit_scope.candidate_base_hash != context.state.candidate_base_hash:
        return error(
            call,
            "PLAN_BASE_HASH_MISMATCH",
            "Edit plan does not match the candidate base hash",
            cause={
                "expected_base_hash": context.state.candidate_base_hash,
                "actual_base_hash": plan.edit_scope.candidate_base_hash,
            },
        )
    dropped = _dropped_explicit_requirements(context.state.workflow_contract, plan)
    if dropped:
        return error(
            call,
            "EXPLICIT_REQUIREMENT_DROPPED",
            "A revision cannot silently remove explicit user requirements",
            cause={"requirement_ids": dropped},
        )
    revision = current_revision + 1
    resolved_resources = _resolve_resources(plan.resources, context)
    unresolved_resources = sorted(_resource_label(resource) for resource in resolved_resources if not resource.verified)
    if plan.status == "complete" and unresolved_resources:
        return error(
            call,
            "PLAN_RESOURCE_UNRESOLVED",
            "Complete workflow plans require server-verified resources",
            cause={"resources": unresolved_resources},
        )
    body = plan.model_dump(mode="json")
    body["resources"] = [resource.model_dump(mode="json") for resource in resolved_resources]
    contract_hash = canonical_workflow_contract_hash(body, revision=revision)
    contract = WorkflowContract(
        **body,
        protocol_version=WORKFLOW_CONTRACT_PROTOCOL_VERSION,
        revision=revision,
        contract_hash=contract_hash,
    )
    context.state.workflow_contract = contract.model_dump(mode="json")
    context.state.contract_revision = revision
    context.state.contract_hash = contract_hash
    context.state.attempts.clear()
    return ok(
        call,
        changed=False,
        content={
            "schema_version": plan.schema_version,
            "revision": revision,
            "status": plan.status,
            "operation": plan.operation,
            "contract_hash": contract_hash,
        },
    )


def workflow_plan_mutation_error(call: ToolCall, context: ToolContext) -> ToolResult | None:
    """Enforce plan readiness and local-edit scope before a graph mutation."""
    if call["name"] not in _GRAPH_MUTATION_TOOLS or context.state.contract_protocol_version is None:
        return None
    raw_contract = context.state.workflow_contract
    if raw_contract is None:
        return error(call, "WORKFLOW_PLAN_REQUIRED", "Submit a workflow plan before mutating the candidate graph")
    try:
        contract = WorkflowContract.model_validate(raw_contract)
    except ValidationError:
        return error(call, "INVALID_WORKFLOW_PLAN", "Persisted workflow contract is invalid")
    node_ids = _mutation_node_ids(call)
    if contract.operation == "edit":
        assert contract.edit_scope is not None
        allowed = set(contract.edit_scope.allowed_node_ids)
        affected = set(contract.edit_scope.affected_downstream_ids)
        outside = sorted(node_ids - allowed - affected)
        if outside:
            return error(
                call,
                "PLAN_EDIT_SCOPE_VIOLATION",
                "Mutation is outside the declared local-edit scope",
                cause={"node_ids": outside, "allowed_node_ids": sorted(allowed)},
            )
    planned_by_id = {node.id: node for node in contract.nodes}
    if call["name"] in _NODE_BUILD_TOOLS:
        undeclared = sorted(node_ids - planned_by_id.keys())
        if undeclared:
            return error(
                call,
                "PLAN_MUTATION_NOT_DECLARED",
                "Node build is not declared by the current workflow plan",
                cause={"node_ids": undeclared},
            )
    if call["name"] == "connect":
        arguments = call["arguments"]
        source = arguments.get("source")
        target = arguments.get("target")
        source_handle = arguments.get("source_handle")
        declared = any(
            edge.source == source and edge.target == target and edge.source_handle == source_handle
            for edge in contract.edges
        )
        if not declared:
            return error(
                call,
                "PLAN_MUTATION_NOT_DECLARED",
                "Control edge is not declared by the current workflow plan",
                cause={"edge": {"source": source, "target": target, "source_handle": source_handle}},
            )
    for node_id in sorted(node_ids):
        planned = planned_by_id.get(node_id)
        if planned is not None and planned.unresolved:
            return error(
                call,
                "PLAN_NODE_UNRESOLVED",
                f"Plan node {node_id!r} still has unresolved requirements",
                cause={"node_id": node_id, "unresolved": list(planned.unresolved)},
            )
        unverified = [
            _resource_label(resource)
            for resource in contract.resources
            if resource.consumer_id == node_id and not resource.verified
        ]
        if unverified:
            return error(
                call,
                "PLAN_NODE_UNRESOLVED",
                f"Plan node {node_id!r} has unverified resources",
                cause={"node_id": node_id, "unresolved_resources": sorted(unverified)},
            )
    mismatch_issues = _mutation_mismatch_issues(call, planned_by_id, contract.resources, context)
    if mismatch_issues:
        return error(
            call,
            "PLAN_MUTATION_MISMATCH",
            "Graph mutation does not match the submitted workflow plan",
            cause={"issues": mismatch_issues},
        )
    return None


def workflow_contract_finish_error(call: ToolCall, context: ToolContext) -> ToolResult | None:
    """Require a complete contract only for conversations on the new protocol."""
    if context.state.contract_protocol_version is None:
        return None
    raw_contract = context.state.workflow_contract
    if raw_contract is None:
        return error(call, "WORKFLOW_PLAN_REQUIRED", "Submit a complete workflow plan before finish")
    try:
        contract = WorkflowContract.model_validate(raw_contract)
    except ValidationError:
        return error(call, "INVALID_WORKFLOW_PLAN", "Persisted workflow contract is invalid")
    if contract.status != "complete":
        return error(
            call,
            "WORKFLOW_PLAN_INCOMPLETE",
            "Workflow plan is still draft",
            cause={"contract_revision": contract.revision, "status": contract.status},
        )
    return None


def _mutation_node_ids(call: ToolCall) -> set[str]:
    arguments = call["arguments"]
    if call["name"] in {"build_node", "build_tool_node", "build_agent_node", "build_loop", "build_iteration"}:
        value = arguments.get("id")
        return {value} if isinstance(value, str) and value else set()
    if call["name"] == "delete_node":
        value = arguments.get("node_id")
        return {value} if isinstance(value, str) and value else set()
    return {value for key in ("source", "target") if isinstance((value := arguments.get(key)), str) and value}


def _resolve_resources(resources: list[WorkflowResource], context: ToolContext) -> list[ResolvedWorkflowResource]:
    resolved: list[ResolvedWorkflowResource] = []
    models = {(entry["provider"], entry["name"]) for entry in context.env.agent_model_entries}
    for resource in resources:
        verified: bool
        unavailable: bool
        if isinstance(resource, WorkflowDatasetResource):
            installed_dataset_ids = context.env.installed_dataset_ids
            unavailable = not context.env.knowledge_available or installed_dataset_ids is None
            verified = context.env.knowledge_available and (
                installed_dataset_ids is not None and resource.dataset_id in installed_dataset_ids
            )
            resolved.append(
                ResolvedDatasetResource(
                    **resource.model_dump(),
                    verified=verified,
                    unresolved_reason=None if verified else "catalogue_unavailable" if unavailable else "not_found",
                )
            )
        elif isinstance(resource, WorkflowToolResource):
            installed_tools = context.env.installed_tools
            unavailable = not context.env.tools_available or installed_tools is None
            verified = context.env.tools_available and (
                installed_tools is not None and (resource.provider_name, resource.tool_name) in installed_tools
            )
            resolved.append(
                ResolvedToolResource(
                    **resource.model_dump(),
                    verified=verified,
                    unresolved_reason=None if verified else "catalogue_unavailable" if unavailable else "not_found",
                )
            )
        else:
            unavailable = not context.env.models_available
            verified = not unavailable and (resource.provider, resource.name) in models
            resolved.append(
                ResolvedModelResource(
                    **resource.model_dump(),
                    verified=verified,
                    unresolved_reason=None if verified else "catalogue_unavailable" if unavailable else "not_found",
                )
            )
    return resolved


def _resource_label(resource: ResolvedWorkflowResource) -> str:
    if isinstance(resource, ResolvedDatasetResource):
        return f"dataset:{resource.dataset_id}"
    if isinstance(resource, ResolvedToolResource):
        return f"tool:{resource.provider_name}/{resource.tool_name}"
    return f"model:{resource.provider}/{resource.name}"


def _mutation_mismatch_issues(
    call: ToolCall,
    planned_by_id: dict[str, WorkflowPlanNode],
    resources: list[ResolvedWorkflowResource],
    context: ToolContext,
) -> list[dict[str, object]]:
    if call["name"] not in _NODE_BUILD_TOOLS:
        return []
    node_id = call["arguments"].get("id")
    if not isinstance(node_id, str) or (planned := planned_by_id.get(node_id)) is None:
        return []
    arguments = call["arguments"]
    mode = arguments.get("mode")
    actual_type = {
        "build_tool_node": "tool",
        "build_agent_node": "agent",
        "build_loop": "loop",
        "build_iteration": "iteration",
    }.get(call["name"], arguments.get("type"))
    if call["name"] == "build_node" and mode == "update":
        existing = find_node(context.state.graph, node_id)
        actual_type = existing["data"].get("type") if existing is not None else None
    issues: list[dict[str, object]] = []
    _append_mismatch(issues, "type", planned.type, actual_type)
    if call["name"] == "build_node":
        intent = arguments.get("intent")
        intent = intent if isinstance(intent, dict) else {}
        _append_mismatch(
            issues,
            "objective",
            normalize_requirement_evidence(planned.objective),
            normalize_requirement_evidence(str(intent.get("objective") or "")),
        )
        _append_mismatch(issues, "inputs", _planned_inputs(planned), _raw_inputs(intent.get("inputs")))
        _append_mismatch(issues, "outputs", _planned_outputs(planned), _raw_outputs(intent.get("outputs")))
        structure = intent.get("structure")
        if mode != "update" or "structure" in intent:
            actual_structure = structure.get("kind") if isinstance(structure, dict) else None
            if planned.structure_kind is not None:
                _append_mismatch(issues, "structure_kind", planned.structure_kind, actual_structure)
            expected_models = sorted(
                (resource.provider, resource.name, resource.mode)
                for resource in resources
                if isinstance(resource, ResolvedModelResource) and resource.consumer_id == node_id
            )
            model = structure.get("model") if isinstance(structure, dict) else None
            actual_models = (
                [
                    (
                        str(model.get("provider") or ""),
                        str(model.get("name") or ""),
                        str(model.get("mode") or "chat"),
                    )
                ]
                if isinstance(model, dict)
                else []
            )
            _append_mismatch(issues, "resources.models", expected_models, actual_models)
    elif call["name"] == "build_agent_node":
        _append_mismatch(
            issues,
            "objective",
            normalize_requirement_evidence(planned.objective),
            normalize_requirement_evidence(str(arguments.get("instruction") or "")),
        )
        _append_mismatch(issues, "inputs", _planned_inputs(planned), _raw_inputs(arguments.get("inputs")))
        _append_mismatch(issues, "outputs", _planned_outputs(planned), _raw_outputs(arguments.get("outputs")))
    elif call["name"] in {"build_loop", "build_iteration"}:
        _append_mismatch(issues, "outputs", _planned_outputs(planned), _raw_outputs(arguments.get("outputs")))
    expected_tools = sorted(
        (resource.provider_name, resource.tool_name)
        for resource in resources
        if isinstance(resource, ResolvedToolResource) and resource.consumer_id == node_id
    )
    if call["name"] == "build_tool_node":
        tool = arguments.get("tool")
        actual_tools = (
            [(str(tool.get("provider_name") or ""), str(tool.get("tool_name") or ""))] if isinstance(tool, dict) else []
        )
        _append_mismatch(issues, "resources.tools", expected_tools, actual_tools)
    elif call["name"] == "build_agent_node":
        actual_tools = _raw_tool_bindings(arguments.get("tools")) + _raw_tool_bindings(arguments.get("mcp_tools"))
        _append_mismatch(issues, "resources.tools", expected_tools, sorted(actual_tools))
        expected_datasets = sorted(
            resource.dataset_id
            for resource in resources
            if isinstance(resource, ResolvedDatasetResource) and resource.consumer_id == node_id
        )
        if mode != "update" or "knowledge" in arguments:
            actual_datasets = _raw_agent_datasets(arguments.get("knowledge"))
            _append_mismatch(issues, "resources.datasets", expected_datasets, actual_datasets)
        expected_models = sorted(
            (resource.provider, resource.name, resource.mode)
            for resource in resources
            if isinstance(resource, ResolvedModelResource) and resource.consumer_id == node_id
        )
        model = arguments.get("model")
        actual_models = (
            [
                (
                    str(model.get("provider") or ""),
                    str(model.get("name") or ""),
                    str(model.get("mode") or "chat"),
                )
            ]
            if isinstance(model, dict)
            else []
        )
        _append_mismatch(issues, "resources.models", expected_models, actual_models)
    return issues


def _planned_inputs(node: WorkflowPlanNode) -> list[tuple[tuple[str, ...], str]]:
    return [(item.source, item.role) for item in node.inputs]


def _raw_inputs(value: object) -> list[tuple[tuple[str, ...], str]]:
    if not isinstance(value, list):
        return []
    return [
        (tuple(source), str(item.get("role") or ""))
        for item in value
        if isinstance(item, dict) and isinstance((source := item.get("source")), (list, tuple))
    ]


def _planned_outputs(node: WorkflowPlanNode) -> list[tuple[str, str]]:
    return [(item.name, item.type) for item in node.outputs]


def _raw_outputs(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    return [(str(item.get("name") or ""), str(item.get("type") or "")) for item in value if isinstance(item, dict)]


def _raw_tool_bindings(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        (str(item.get("provider_name") or ""), str(item.get("tool_name") or ""))
        for item in value
        if isinstance(item, dict)
    ]


def _raw_agent_datasets(value: object) -> list[str]:
    if not isinstance(value, dict) or value.get("operation") != "replace":
        return []
    sets = value.get("sets")
    if not isinstance(sets, list):
        return []
    dataset_ids: set[str] = set()
    for item in sets:
        if not isinstance(item, dict) or not isinstance(item.get("dataset_ids"), list):
            continue
        dataset_ids.update(str(dataset_id) for dataset_id in item["dataset_ids"])
    return sorted(dataset_ids)


def _append_mismatch(
    issues: list[dict[str, object]],
    field: str,
    expected: object,
    actual: object,
) -> None:
    if expected != actual:
        issues.append({"field": field, "expected": expected, "actual": actual})


def _dropped_explicit_requirements(current: dict[str, object] | None, proposed: WorkflowPlan) -> list[str]:
    if current is None:
        return []
    old_requirements = current.get("requirements")
    if not isinstance(old_requirements, list):
        return []
    retained = {requirement.id for requirement in proposed.requirements}
    valid_superseders = [
        requirement for requirement in proposed.requirements if requirement.provenance == "explicit_user"
    ]
    dropped: list[str] = []
    for raw in old_requirements:
        if not isinstance(raw, dict) or raw.get("provenance") != "explicit_user":
            continue
        requirement_id = raw.get("id")
        source_turn_id = raw.get("source_turn_id")
        if not isinstance(requirement_id, str) or requirement_id in retained:
            continue
        was_explicitly_replaced = any(
            requirement_id in requirement.supersedes and requirement.source_turn_id != source_turn_id
            for requirement in valid_superseders
        )
        if not was_explicitly_replaced:
            dropped.append(requirement_id)
    return sorted(dropped)


def canonical_workflow_contract_hash(plan: dict[str, object], *, revision: int) -> str:
    """Return the protocol-1 hash for a plan body without contract metadata."""
    canonical = json.dumps(
        {"protocol_version": WORKFLOW_CONTRACT_PROTOCOL_VERSION, "revision": revision, **plan},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def workflow_contract_hash_is_valid(contract: WorkflowContract) -> bool:
    """Verify the stored hash against the complete canonical contract body."""
    body = contract.model_dump(mode="json")
    revision = contract.revision
    expected = contract.contract_hash
    for field in ("protocol_version", "revision", "contract_hash"):
        body.pop(field, None)
    return canonical_workflow_contract_hash(body, revision=revision) == expected
