"""Pure reconciliation between a Workflow Assist contract and a candidate graph.

The report is the shared completion seam for Agent ``finish``, durable worker
completion, and Apply.  It checks only mechanically observable facts.  A
business or runtime assertion remains ``unverified`` until its dedicated
acceptance layer supplies evidence; static inspection never upgrades prose to
proof.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from pydantic import ValidationError

from core.workflow.generator.compiler.agent_knowledge import collect_agent_knowledge_dataset_ids
from core.workflow.generator.contracts.workflow_contract import (
    ResolvedDatasetResource,
    ResolvedModelResource,
    ResolvedToolResource,
    WorkflowContract,
    workflow_contract_hash_is_valid,
)
from core.workflow.generator.types import WorkflowGenerationMode
from core.workflow.generator.variables.declarations import declared_output_type, declared_outputs
from core.workflow.generator.variables.syntax import collect_references
from core.workflow.generator.variables.variable_registry import canonical_registry_type

WORKFLOW_RECONCILIATION_VERSION = 1
ReconciliationStatus = Literal["satisfied", "missing", "conflict", "unverified"]


class ReconciliationCheck(TypedDict):
    id: str
    category: str
    status: ReconciliationStatus
    blocking: bool
    detail: str
    requirement_ids: list[str]


class ReconciliationReport(TypedDict):
    version: int
    passed: bool
    checks: list[ReconciliationCheck]
    summary: dict[str, int]


def reconcile_workflow_contract(
    *,
    contract: Mapping[str, object] | WorkflowContract,
    graph: Mapping[str, object],
    mode: WorkflowGenerationMode,
    candidate_base_hash: str | None = None,
    installed_tools: set[tuple[str, str]] | None = None,
    installed_dataset_ids: set[str] | None = None,
    installed_models: set[tuple[str, str]] | None = None,
) -> ReconciliationReport:
    """Compare one complete contract with observable graph and catalogue facts.

    ``None`` catalogues mean that membership cannot be refreshed at this
    boundary.  The stored server verification is retained but reported as
    unverified only when it was already unresolved.  Supplied catalogues are
    authoritative and can invalidate formerly valid bindings.
    """
    parsed = contract if isinstance(contract, WorkflowContract) else _parse_contract(contract)
    if parsed is None:
        return _report([_check("contract", "contract", "conflict", True, "Workflow contract is invalid")])
    if not workflow_contract_hash_is_valid(parsed):
        return _report([_check("contract:hash", "contract", "conflict", True, "Workflow contract hash is invalid")])

    nodes = _graph_nodes(graph)
    if nodes is None:
        return _report([_check("graph", "graph", "conflict", True, "Candidate graph nodes are invalid")])
    edges = _graph_edges(graph)
    if edges is None:
        return _report([_check("graph:edges", "edge", "conflict", True, "Candidate graph edges are invalid")])

    checks: list[ReconciliationCheck] = []
    planned_ids = {node.id for node in parsed.nodes}
    top_level_ids = {node_id for node_id, node in nodes.items() if not _parent_id(node)}
    for planned in parsed.nodes:
        actual = nodes.get(planned.id)
        if actual is None:
            checks.append(
                _check(
                    f"node:{planned.id}",
                    "node",
                    "missing",
                    True,
                    f"Planned node {planned.id!r} is missing",
                    planned.requirement_ids,
                )
            )
            continue
        actual_type = _node_type(actual)
        checks.append(
            _check(
                f"node:{planned.id}",
                "node",
                "satisfied" if actual_type == planned.type else "conflict",
                True,
                f"Expected type {planned.type!r}; observed {actual_type!r}",
                planned.requirement_ids,
            )
        )
        actual_refs = {(source, *output.split(".")) for source, output in collect_references(_node_data(actual))}
        planned_refs = {item.source for item in planned.inputs}
        for selector in sorted(planned_refs):
            checks.append(
                _check(
                    f"input:{planned.id}:{'.'.join(selector)}",
                    "input",
                    "satisfied" if selector in actual_refs else "missing",
                    True,
                    f"Input selector {'.'.join(selector)!r}",
                    planned.requirement_ids,
                )
            )
        for selector in sorted(actual_refs - planned_refs):
            checks.append(
                _check(
                    f"input:{planned.id}:{'.'.join(selector)}",
                    "input",
                    "conflict",
                    True,
                    f"Candidate has undeclared input selector {'.'.join(selector)!r}",
                    planned.requirement_ids,
                )
            )
        actual_outputs = set(_declared_outputs(actual))
        for output in planned.outputs:
            check_id = f"output:{planned.id}:{output.name}"
            if output.name not in actual_outputs:
                checks.append(
                    _check(
                        check_id,
                        "output",
                        "missing",
                        True,
                        f"Output {output.name!r} is missing",
                        planned.requirement_ids,
                    )
                )
                continue
            actual_output_type = _declared_output_type(actual, output.name)
            if actual_output_type is None:
                checks.append(
                    _check(
                        check_id,
                        "output",
                        "unverified",
                        True,
                        f"Output {output.name!r} type is unknown",
                        planned.requirement_ids,
                    )
                )
                continue
            expected_type = canonical_registry_type(output.type)
            observed_type = canonical_registry_type(actual_output_type)
            checks.append(
                _check(
                    check_id,
                    "output",
                    "satisfied" if expected_type == observed_type else "conflict",
                    True,
                    f"Expected type {expected_type!r}; observed {observed_type!r}",
                    planned.requirement_ids,
                )
            )

    if parsed.operation == "rebuild":
        for node_id in sorted(top_level_ids - planned_ids):
            checks.append(
                _check(
                    f"node:{node_id}",
                    "node",
                    "conflict",
                    True,
                    f"Candidate contains undeclared top-level node {node_id!r}",
                )
            )
    elif parsed.edit_scope is not None:
        checks.append(
            _check(
                "edit:base_hash",
                "edit_scope",
                "satisfied" if parsed.edit_scope.candidate_base_hash == candidate_base_hash else "conflict",
                True,
                "Local edit base hash must match the candidate base",
            )
        )

    planned_edges = {(edge.source, edge.target, edge.source_handle) for edge in parsed.edges}
    for edge in sorted(planned_edges):
        checks.append(
            _check(
                f"edge:{edge[0]}:{edge[1]}:{edge[2] or ''}",
                "edge",
                "satisfied" if edge in edges else "missing",
                True,
                f"Control edge {edge!r}",
            )
        )
    if parsed.operation == "rebuild":
        for edge in sorted(edges - planned_edges):
            checks.append(
                _check(
                    f"edge:{edge[0]}:{edge[1]}:{edge[2] or ''}",
                    "edge",
                    "conflict",
                    True,
                    f"Candidate contains undeclared control edge {edge!r}",
                )
            )

    terminal_type = "end" if mode == "workflow" else "answer"
    for output in parsed.final_outputs:
        source_node = nodes.get(output.source[0])
        source_type = _node_type(source_node) if source_node is not None else None
        # A nested selector still originates from one declared top-level
        # output.  Joining every path segment would incorrectly look for an
        # output literally named ``result.customer.name``.
        output_name = output.source[1]
        present = source_node is not None and output_name in _declared_outputs(source_node)
        final_status: ReconciliationStatus = "satisfied" if present and source_type == terminal_type else "conflict"
        checks.append(
            _check(
                f"final_output:{output.name}",
                "final_output",
                final_status,
                True,
                f"Expected {terminal_type!r} output {'.'.join(output.source)!r}",
            )
        )

    actual_resources = _actual_resources(nodes)
    planned_resources: set[tuple[str, ...]] = set()
    for resource in parsed.resources:
        key = _resource_key(resource)
        planned_resources.add(key)
        resource_status: ReconciliationStatus
        detail = f"Resource {key!r}"
        if not resource.verified:
            resource_status = "unverified"
        elif key not in actual_resources:
            resource_status = "missing"
        elif not _resource_is_current(
            resource,
            installed_tools=installed_tools,
            installed_dataset_ids=installed_dataset_ids,
            installed_models=installed_models,
        ):
            resource_status = "conflict"
        else:
            resource_status = "satisfied"
        checks.append(_check(f"resource:{':'.join(key)}", "resource", resource_status, True, detail))
    if parsed.operation == "rebuild":
        for key in sorted(actual_resources - planned_resources):
            checks.append(
                _check(
                    f"resource:{':'.join(key)}",
                    "resource",
                    "conflict",
                    True,
                    f"Candidate contains undeclared resource {key!r}",
                )
            )

    requirement_statuses: dict[str, list[ReconciliationStatus]] = {}
    for item in checks:
        for requirement_id in item["requirement_ids"]:
            requirement_statuses.setdefault(requirement_id, []).append(item["status"])
    for planned_check in parsed.checks:
        statuses = [
            status
            for requirement_id in planned_check.requirement_ids
            for status in requirement_statuses.get(requirement_id, [])
        ]
        if planned_check.level != "static":
            requirement_status: ReconciliationStatus = "unverified"
            blocking = False
        elif any(status in {"missing", "conflict", "unverified"} for status in statuses):
            requirement_status = "conflict"
            blocking = True
        else:
            requirement_status = "satisfied"
            blocking = True
        checks.append(
            _check(
                f"check:{planned_check.id}",
                "requirement",
                requirement_status,
                blocking,
                planned_check.description,
                planned_check.requirement_ids,
            )
        )
    return _report(checks)


def _parse_contract(contract: Mapping[str, object]) -> WorkflowContract | None:
    try:
        return WorkflowContract.model_validate(contract)
    except ValidationError:
        return None


def _graph_nodes(graph: Mapping[str, object]) -> dict[str, Mapping[str, Any]] | None:
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        return None
    nodes: dict[str, Mapping[str, Any]] = {}
    for raw in raw_nodes:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("id"), str) or raw["id"] in nodes:
            return None
        nodes[raw["id"]] = raw
    return nodes


def _graph_edges(graph: Mapping[str, object]) -> set[tuple[str, str, str | None]] | None:
    raw_edges = graph.get("edges")
    if not isinstance(raw_edges, list):
        return None
    edges: set[tuple[str, str, str | None]] = set()
    for raw in raw_edges:
        if (
            not isinstance(raw, Mapping)
            or not isinstance(raw.get("source"), str)
            or not isinstance(raw.get("target"), str)
        ):
            return None
        handle = raw.get("sourceHandle") or raw.get("source_handle")
        normalized_handle = None if handle in {None, "", "source"} else str(handle)
        edges.add((raw["source"], raw["target"], normalized_handle))
    return edges


def _node_data(node: Mapping[str, Any]) -> dict[str, Any]:
    data = node.get("data")
    return dict(data) if isinstance(data, Mapping) else {}


def _node_type(node: Mapping[str, Any] | None) -> str | None:
    if node is None:
        return None
    data = node.get("data")
    value = data.get("type") if isinstance(data, Mapping) else node.get("type")
    return str(value) if value else None


def _parent_id(node: Mapping[str, Any]) -> str | None:
    data = node.get("data")
    value = node.get("parentId") or (data.get("parentId") if isinstance(data, Mapping) else None)
    return str(value) if value else None


def _declared_outputs(node: Mapping[str, Any]) -> list[str]:
    data = _node_data(node)
    if _node_type(node) == "end":
        outputs = data.get("outputs")
        return [
            str(item["variable"])
            for item in outputs or []
            if isinstance(item, Mapping) and isinstance(item.get("variable"), str)
        ]
    if _node_type(node) == "answer":
        return ["answer"]
    return declared_outputs(dict(node))


def _declared_output_type(node: Mapping[str, Any], output_name: str) -> str | None:
    data = _node_data(node)
    if _node_type(node) == "end":
        for item in data.get("outputs") or []:
            if isinstance(item, Mapping) and item.get("variable") == output_name:
                value_type = item.get("value_type")
                return str(value_type) if value_type else None
        return None
    if _node_type(node) == "answer" and output_name == "answer":
        return "string"
    return declared_output_type(dict(node), output_name)


def _actual_resources(nodes: Mapping[str, Mapping[str, Any]]) -> set[tuple[str, ...]]:
    resources: set[tuple[str, ...]] = set()
    for node_id, node in nodes.items():
        data = _node_data(node)
        node_type = _node_type(node)
        model = data.get("model")
        if isinstance(model, Mapping) and model.get("provider") and model.get("name"):
            resources.add(
                ("model", node_id, str(model["provider"]), str(model["name"]), str(model.get("mode") or "chat"))
            )
        if node_type == "tool" and data.get("tool_name"):
            provider = data.get("provider_id") or data.get("provider_name")
            if provider:
                resources.add(("tool", node_id, str(provider), str(data["tool_name"])))
        for binding in data.get("dify_tools") or []:
            if isinstance(binding, Mapping) and binding.get("tool_name"):
                provider = binding.get("provider_id") or binding.get("provider_name")
                if provider:
                    resources.add(("tool", node_id, str(provider), str(binding["tool_name"])))
        dataset_ids = collect_agent_knowledge_dataset_ids(data)
        if node_type == "knowledge-retrieval" and isinstance(data.get("dataset_ids"), list):
            dataset_ids.extend(str(item) for item in data["dataset_ids"] if isinstance(item, str))
        resources.update(("dataset", node_id, dataset_id) for dataset_id in set(dataset_ids))
    return resources


def _resource_key(resource: ResolvedDatasetResource | ResolvedToolResource | ResolvedModelResource) -> tuple[str, ...]:
    if isinstance(resource, ResolvedDatasetResource):
        return ("dataset", resource.consumer_id, resource.dataset_id)
    if isinstance(resource, ResolvedToolResource):
        return ("tool", resource.consumer_id, resource.provider_name, resource.tool_name)
    return ("model", resource.consumer_id, resource.provider, resource.name, resource.mode)


def _resource_is_current(
    resource: ResolvedDatasetResource | ResolvedToolResource | ResolvedModelResource,
    *,
    installed_tools: set[tuple[str, str]] | None,
    installed_dataset_ids: set[str] | None,
    installed_models: set[tuple[str, str]] | None,
) -> bool:
    if isinstance(resource, ResolvedDatasetResource):
        return installed_dataset_ids is None or resource.dataset_id in installed_dataset_ids
    if isinstance(resource, ResolvedToolResource):
        return installed_tools is None or (resource.provider_name, resource.tool_name) in installed_tools
    return installed_models is None or (resource.provider, resource.name) in installed_models


def _check(
    check_id: str,
    category: str,
    status: ReconciliationStatus,
    blocking: bool,
    detail: str,
    requirement_ids: list[str] | None = None,
) -> ReconciliationCheck:
    return {
        "id": check_id,
        "category": category,
        "status": status,
        "blocking": blocking,
        "detail": detail,
        "requirement_ids": list(requirement_ids or []),
    }


def _report(checks: list[ReconciliationCheck]) -> ReconciliationReport:
    counts = Counter(check["status"] for check in checks)
    return {
        "version": WORKFLOW_RECONCILIATION_VERSION,
        "passed": not any(check["blocking"] and check["status"] != "satisfied" for check in checks),
        "checks": checks,
        "summary": {
            "satisfied": counts["satisfied"],
            "missing": counts["missing"],
            "conflict": counts["conflict"],
            "unverified": counts["unverified"],
        },
    }
