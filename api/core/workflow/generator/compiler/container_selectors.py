"""Allocate child identities and rewrite local references into graph selectors."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from core.workflow.generator.compiler.container_types import ContainerCompileRequest
from core.workflow.generator.compiler.container_values import _ID_SAFE
from core.workflow.generator.compiler.intents.container_intent import (
    LoopBuildIntent,
)
from core.workflow.generator.variables.variable_references import VariableReferences


def allocate_child_ids(request: ContainerCompileRequest) -> dict[str, str]:
    """Map each child ref to a stable node id; stored refs win on update."""
    used = {str(node["id"]) for node in request.frozen_graph["nodes"] if isinstance(node.get("id"), str)}
    used.discard(request.container_id)
    ref_map: dict[str, str] = {}
    for child in request.intent.children:
        stored = request.existing_child_ids.get(child.ref)
        if isinstance(stored, str) and stored:
            ref_map[child.ref] = stored
            used.add(stored)
            continue
        candidate = f"{request.container_id}_{_safe_ref(child.ref)}"
        unique = candidate
        suffix = 2
        while unique in used:
            unique = f"{candidate}_{suffix}"
            suffix += 1
        ref_map[child.ref] = unique
        used.add(unique)
    return ref_map


def rewrite_selectors(
    selectors: Sequence[Sequence[str]],
    *,
    ref_map: Mapping[str, str],
    container_id: str,
    loop_variable_labels: frozenset[str],
) -> list[list[str]]:
    """Rewrite child refs and bare loop-variable labels to real ids."""
    return [
        _rewrite_selector(
            list(selector),
            ref_map=ref_map,
            container_id=container_id,
            loop_variable_labels=loop_variable_labels,
        )
        for selector in selectors
    ]


def _rewrite_value(
    value: object,
    *,
    ref_map: Mapping[str, str],
    container_id: str,
    loop_variable_labels: frozenset[str],
) -> Any:
    if isinstance(value, str):
        return VariableReferences._VAR_REF_RE.sub(
            lambda match: _rewrite_placeholder(
                match,
                ref_map=ref_map,
                container_id=container_id,
                loop_variable_labels=loop_variable_labels,
            ),
            value,
        )
    if _is_selector(value):
        return _rewrite_selector(
            list(cast(Sequence[str], value)),
            ref_map=ref_map,
            container_id=container_id,
            loop_variable_labels=loop_variable_labels,
        )
    if isinstance(value, dict):
        return {
            key: _rewrite_value(
                item,
                ref_map=ref_map,
                container_id=container_id,
                loop_variable_labels=loop_variable_labels,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_value(
                item,
                ref_map=ref_map,
                container_id=container_id,
                loop_variable_labels=loop_variable_labels,
            )
            for item in value
        ]
    return value


def _rewrite_placeholder(
    match: re.Match[str],
    *,
    ref_map: Mapping[str, str],
    container_id: str,
    loop_variable_labels: frozenset[str],
) -> str:
    source = match.group(1)
    output = match.group(2)
    if source in ref_map:
        source = ref_map[source]
    elif source in loop_variable_labels:
        output = f"{source}.{output}"
        source = container_id
    return f"{{{{#{source}.{output}#}}}}"


def _rewrite_selector(
    selector: list[str],
    *,
    ref_map: Mapping[str, str],
    container_id: str,
    loop_variable_labels: frozenset[str],
) -> list[str]:
    if not selector:
        return selector
    if len(selector) == 1 and selector[0] in loop_variable_labels:
        return [container_id, selector[0]]
    head = selector[0]
    if head in ref_map:
        return [ref_map[head], *selector[1:]]
    if head in loop_variable_labels:
        return [container_id, *selector]
    return list(selector)


def _is_selector(value: object) -> bool:
    return isinstance(value, (list, tuple)) and bool(value) and all(isinstance(part, str) and part for part in value)


def _rewrite_labels(request: ContainerCompileRequest) -> frozenset[str]:
    intent = request.intent
    if isinstance(intent, LoopBuildIntent):
        return frozenset(item.label for item in intent.loop_variables)
    return frozenset({"item", "index"})


def _safe_ref(ref: str) -> str:
    return "".join(char if char in _ID_SAFE else "_" for char in ref) or "child"
