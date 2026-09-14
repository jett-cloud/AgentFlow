"""Normalize generated references while preserving selector scope and declared outputs."""

import logging
import re
from typing import Any

from core.workflow.generator.types import WorkflowGenerationMode
from graphon.enums import BuiltinNodeTypes

logger = logging.getLogger(__name__)

from core.workflow.generator.variables.declarations import _declares_variable, _sole_declared_variable
from core.workflow.generator.variables.syntax import (
    _CONTAINER_SCOPE_VARS,
    _ID_FIELDS,
    _INVALID_ID_CHARS_RE,
    _LENIENT_VAR_REF_RE,
    _VAR_REF_RE,
    _collect_refs_in_data,
    _field_scan_kind,
    _is_multi_wrapped_selectors,
    _is_selector_list,
    _is_sys_query_selector,
    _is_sys_query_token,
    _is_wrapped_single_selector,
    _output_basename,
)


def _inject_start_variable(start_node: dict[str, Any], var: str) -> None:
    """Add a default paragraph input so a Start reference resolves."""
    data = start_node.setdefault("data", {})
    existing = data.setdefault("variables", [])
    if any(isinstance(value, dict) and value.get("variable") == var for value in existing):
        return
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", var).lower()
    label = " ".join(part.capitalize() for part in snake.split("_") if part)
    existing.append(
        {
            "variable": var,
            "label": label,
            "type": "paragraph",
            "required": True,
            "max_length": 4096,
            "options": [],
        }
    )


def _normalize_sys_query_references(
    *,
    nodes: list[dict[str, Any]],
    mode: WorkflowGenerationMode,
) -> None:
    """Normalize malformed ``sys.query`` references without changing their intent.

    Chatflows expose ``sys.query`` directly. Plain workflows do not, so
    their query references become a Start-node input and the existing
    reconciliation pass declares that input immediately afterwards.
    """
    if mode == "advanced-chat":
        target_node_id = "sys"
    else:
        start_node = next(
            (node for node in nodes if node.get("data", {}).get("type") == BuiltinNodeTypes.START),
            None,
        )
        start_node_id = start_node.get("id") if start_node else None
        if not isinstance(start_node_id, str) or not start_node_id:
            return
        target_node_id = start_node_id

    for node in nodes:
        data = node.get("data")
        if isinstance(data, dict):
            _normalize_sys_query_reference_in_data(data, target_node_id=target_node_id)


def _normalize_sys_query_reference_in_data(
    value: Any,
    *,
    target_node_id: str,
    parent: dict[str, Any] | None = None,
    key: str = "",
) -> Any:
    """Rewrite query placeholders and selectors at any node-data depth.

    Some node schemas store selectors inside another list, for example a
    parameter extractor's ``query`` or a variable aggregator's
    ``variables``. Literal string-list fields opt out so an option list
    such as ``["sys", "query"]`` is preserved.
    """
    target_placeholder = f"{{{{#{target_node_id}.query#}}}}"
    if isinstance(value, str):
        if key and _field_scan_kind(key, parent) == "literal":
            return value
        return value.replace("{{#sys.query#}}", target_placeholder).replace("{{#sys,query#}}", target_placeholder)
    if isinstance(value, dict):
        for key, item in list(value.items()):
            kind = _field_scan_kind(key, value)
            if kind in {"skip", "literal"}:
                continue
            if kind in {"selector", "query", "selector_list"} and _is_sys_query_selector(item):
                value[key] = [target_node_id, "query"]
                continue
            if kind == "query" and _is_wrapped_single_selector(item) and _is_sys_query_selector(item[0]):
                value[key] = [target_node_id, "query"]
                continue
            if kind in {"selector", "query"} and isinstance(item, str) and _is_sys_query_token(item):
                value[key] = [target_node_id, "query"]
                continue
            value[key] = _normalize_sys_query_reference_in_data(
                item,
                target_node_id=target_node_id,
                parent=value,
                key=key,
            )
        return value
    if isinstance(value, list):
        kind = _field_scan_kind(key, parent)
        if kind in {"selector", "query"} and _is_sys_query_selector(value):
            return [target_node_id, "query"]
        if kind == "selector_list":
            for index, item in enumerate(value):
                if _is_sys_query_selector(item):
                    value[index] = [target_node_id, "query"]
                else:
                    value[index] = _normalize_sys_query_reference_in_data(
                        item,
                        target_node_id=target_node_id,
                        parent=parent,
                        key=key,
                    )
            return value
        for index, item in enumerate(value):
            value[index] = _normalize_sys_query_reference_in_data(
                item,
                target_node_id=target_node_id,
                parent=parent,
                key=key,
            )
    return value


def _unwrap_single_wrapped_selectors(*, nodes: list[dict[str, Any]]) -> None:
    """Unwrap ``query: [[id, var]]`` into a runtime ``list[str]`` selector."""
    for node in nodes:
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("type") != BuiltinNodeTypes.PARAMETER_EXTRACTOR:
            continue
        query = data.get("query")
        if _is_wrapped_single_selector(query):
            data["query"] = query[0]


def _reconcile_variable_references(*, nodes: list[dict[str, Any]], mode: WorkflowGenerationMode) -> None:
    """
    Apply deterministic repairs to unresolved variable references.

    Missing start-node inputs are added as ``paragraph`` variables. For
    non-start nodes, a mistaken output name is rewritten only when the
    source exposes exactly one declared output. Sources with zero or
    multiple outputs remain untouched so validation fails closed instead
    of guessing which value the workflow should consume.

    For Advanced-Chat mode, ``sys.query`` and ``sys.files`` are always
    treated as resolved without any declaration. Tool nodes' parameter
    references aren't validated here because we don't know each tool's
    schema — the run time validates those.
    """
    nodes_by_id: dict[str, dict[str, Any]] = {n.get("id", ""): n for n in nodes if n.get("id")}
    start_node = next(
        (n for n in nodes if n.get("data", {}).get("type") == BuiltinNodeTypes.START),
        None,
    )

    # Collect every (node_id, var) reference the builder emitted.
    refs: set[tuple[str, str]] = set()
    for node in nodes:
        _collect_refs_in_data(node.get("data") or {}, refs)

    for node_id, var in refs:
        # Advanced-Chat system variables are always resolved.
        if mode == "advanced-chat" and node_id == "sys":
            continue
        target = nodes_by_id.get(node_id)
        if target is None:
            # An edge / data dangling reference — we can't fix it; the
            # structural validator picks this up if it's a topology issue.
            continue
        if _declares_variable(target, var):
            continue
        if start_node is not None and target is start_node:
            _inject_start_variable(start_node, var)
            logger.info("Workflow generator: auto-injected missing start variable %r", var)
            continue

        target_type = (target.get("data") or {}).get("type")
        if (
            target_type in (BuiltinNodeTypes.ITERATION, BuiltinNodeTypes.LOOP)
            and _output_basename(var) in _CONTAINER_SCOPE_VARS
        ):
            # Child-scope vars. Rewriting them to ``output`` creates a
            # self-reference inside the loop; the validator grades scope.
            continue

        replacement = _sole_declared_variable(target)
        if replacement is None:
            continue
        for node in nodes:
            data = node.get("data")
            if isinstance(data, dict):
                _rewrite_variable_reference_in_data(
                    data,
                    node_id=node_id,
                    old_variable=var,
                    new_variable=replacement,
                )
        logger.info(
            "Workflow generator: rewrote unresolved reference %s.%s to sole output %s.%s",
            node_id,
            var,
            node_id,
            replacement,
        )


def _rewrite_variable_reference_in_data(
    value: Any,
    *,
    node_id: str,
    old_variable: str,
    new_variable: str,
    parent: dict[str, Any] | None = None,
    key: str = "",
) -> Any:
    """Rewrite one exact placeholder or selector at any data depth."""
    kind = _field_scan_kind(key, parent) if key else "walk"
    if kind in {"literal", "skip"}:
        return value
    if isinstance(value, str):
        return _VAR_REF_RE.sub(
            lambda match: (
                f"{{{{#{node_id}.{new_variable}#}}}}"
                if match.group(1) == node_id and match.group(2) == old_variable
                else match.group(0)
            ),
            value,
        )
    if kind == "query" and _is_multi_wrapped_selectors(value):
        return value
    if kind in {"selector", "query"} and _is_selector_list(value):
        if value[0] == node_id and ".".join(value[1:]) == old_variable:
            return [node_id, *new_variable.split(".")]
        return value
    if kind == "query" and _is_wrapped_single_selector(value):
        inner = _rewrite_variable_reference_in_data(
            value[0],
            node_id=node_id,
            old_variable=old_variable,
            new_variable=new_variable,
            parent=parent,
            key=key,
        )
        return [inner]
    if isinstance(value, dict):
        for child_key, item in list(value.items()):
            value[child_key] = _rewrite_variable_reference_in_data(
                item,
                node_id=node_id,
                old_variable=old_variable,
                new_variable=new_variable,
                parent=value,
                key=child_key,
            )
        return value
    if isinstance(value, list):
        if kind == "selector_list":
            for index, item in enumerate(value):
                if _is_selector_list(item):
                    if item[0] == node_id and ".".join(item[1:]) == old_variable:
                        value[index] = [node_id, *new_variable.split(".")]
                else:
                    value[index] = _rewrite_variable_reference_in_data(
                        item,
                        node_id=node_id,
                        old_variable=old_variable,
                        new_variable=new_variable,
                        parent=parent,
                        key=key,
                    )
            return value
        for index, item in enumerate(value):
            value[index] = _rewrite_variable_reference_in_data(
                item,
                node_id=node_id,
                old_variable=old_variable,
                new_variable=new_variable,
                parent=parent,
                key=key,
            )
    return value


def _sanitize_node_ids(*, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """
    Rewrite every node id to ``[a-zA-Z0-9_]`` and fix every cross-reference.

    Dify's run-time ``VARIABLE_PATTERN`` accepts only ``[a-zA-Z0-9_]`` in
    the node-id slot of ``{{#…#}}`` placeholders. The builder LLM often
    emits ``node-1`` style ids (and occasionally dots or spaces); left
    unfixed those make every placeholder silently fail at run time, the
    literal ``{{#node-1.var#}}`` survives into the prompt, and the LLM at
    run time echoes it back as the user's output — the bug we are here
    to kill.

    Approach: build a one-to-one ``old → new`` map by dropping the invalid
    characters — collision-safe: when the sanitized id is already taken
    (e.g. the builder emitted BOTH ``node-1`` and ``node1``) a numeric
    suffix keeps the two distinct instead of silently merging every
    reference onto one node. Then rewrite (a) every node ``id``, (b) every
    edge ``source`` / ``target``, (c) every ``parentId`` /
    ``start_node_id`` / ``iteration_id`` / ``loop_id`` inside ``data``,
    (d) every ``{{#…#}}`` reference in any string, (e) every
    ``["node-id", "var"]`` value-selector list. We do NOT rename variable
    names — only ids.
    """
    id_map: dict[str, str] = {}
    # Ids that are already valid are reserved up front so a sanitized id
    # can never collide with an untouched sibling.
    used: set[str] = {
        n["id"] for n in nodes if isinstance(n.get("id"), str) and not _INVALID_ID_CHARS_RE.search(n["id"])
    }
    fallback_seq = 0
    for node in nodes:
        old = node.get("id")
        if not isinstance(old, str) or not _INVALID_ID_CHARS_RE.search(old):
            continue
        base = _INVALID_ID_CHARS_RE.sub("", old)
        if not base:
            # Id was nothing but invalid characters (e.g. "节点", "--").
            fallback_seq += 1
            base = f"node_{fallback_seq}"
        new = base
        suffix = 2
        while new in used:
            new = f"{base}_{suffix}"
            suffix += 1
        used.add(new)
        id_map[old] = new
        node["id"] = new
    if not id_map:
        return

    # Rewrite edges' source / target.
    for edge in edges:
        for key in ("source", "target"):
            v = edge.get(key)
            if isinstance(v, str) and v in id_map:
                edge[key] = id_map[v]
        # Also rewrite the edge id if the builder emitted one referencing
        # the old ids; the dedupe pass later recomputes it anyway, but
        # rewriting here keeps logs sane. Longest-first so an id that is
        # a substring of another (``node-1`` in ``node-12``) can't corrupt
        # the longer match.
        eid = edge.get("id")
        if isinstance(eid, str):
            for old, new in sorted(id_map.items(), key=lambda kv: -len(kv[0])):
                eid = eid.replace(old, new)
            edge["id"] = eid

    # Rewrite every reference inside any node's data (recursively) plus
    # the wrapper-level ``parentId`` — ReactFlow stores parentId on the
    # node wrapper, but the LLM occasionally emits it inside ``data``
    # too. We cover both spots so the strip is symmetric.
    for node in nodes:
        wrapper_parent = node.get("parentId")
        if isinstance(wrapper_parent, str) and wrapper_parent in id_map:
            node["parentId"] = id_map[wrapper_parent]
        data = node.get("data")
        if isinstance(data, dict):
            _rewrite_refs_in_data(data, id_map)


def _rewrite_refs_in_data(
    value: Any,
    id_map: dict[str, str],
    *,
    parent: dict[str, Any] | None = None,
    key: str = "",
) -> None:
    """Rewrite node ids inside selectors and placeholders, not constants."""
    kind = _field_scan_kind(key, parent) if key else "walk"
    if kind == "literal":
        return
    if kind == "skip":
        if isinstance(value, dict):
            for child_key, item in list(value.items()):
                _rewrite_refs_in_data(item, id_map, parent=value, key=child_key)
        return
    match value:
        case dict():
            for child_key, item in list(value.items()):
                if child_key in _ID_FIELDS and isinstance(item, str):
                    for old, new in sorted(id_map.items(), key=lambda kv: -len(kv[0])):
                        if old in item:
                            value[child_key] = item.replace(old, new)
                            item = value[child_key]
                child_kind = _field_scan_kind(child_key, value)
                if child_kind == "literal":
                    continue
                if child_kind in {"selector", "query"} and _is_selector_list(item) and item[0] in id_map:
                    value[child_key] = [id_map[item[0]], *item[1:]]
                    continue
                if child_kind == "query" and _is_wrapped_single_selector(item) and item[0][0] in id_map:
                    value[child_key] = [[id_map[item[0][0]], *item[0][1:]]]
                    continue
                if child_kind == "selector_list" and isinstance(item, list):
                    for index, nested in enumerate(item):
                        if _is_selector_list(nested) and nested[0] in id_map:
                            item[index] = [id_map[nested[0]], *nested[1:]]
                        else:
                            _rewrite_refs_in_data(nested, id_map, parent=value, key=child_key)
                    continue
                if isinstance(item, str) and child_kind != "skip":
                    rewritten = _LENIENT_VAR_REF_RE.sub(lambda m: _rewrite_var_ref(m, id_map), item)
                    if rewritten != item:
                        value[child_key] = rewritten
                else:
                    _rewrite_refs_in_data(item, id_map, parent=value, key=child_key)
        case list():
            for item in value:
                _rewrite_refs_in_data(item, id_map, parent=parent, key=key)


def _rewrite_var_ref(m: re.Match[str], id_map: dict[str, str]) -> str:
    node_id = m.group(1)
    rest = m.group(2)
    new_id = id_map.get(node_id, node_id)
    return f"{{{{#{new_id}.{rest}#}}}}"


def _insert_multi_retrieval_context_templates(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Fan multiple retrieval inputs into an LLM through one template.

    The repair is intentionally narrow: it applies only when at least two
    knowledge-retrieval nodes have direct edges into the same LLM and that
    LLM currently uses one of those results as its enabled context. This
    is enough to repair the builder's lossy single-context output without
    guessing about unrelated retrievals or mutually exclusive branches.
    """
    nodes_by_id: dict[str, dict[str, Any]] = {
        node_id: node for node in nodes if isinstance(node_id := node.get("id"), str)
    }
    used_ids = set(nodes_by_id)
    llm_nodes = [node for node in nodes if node.get("data", {}).get("type") == BuiltinNodeTypes.LLM]

    for llm_node in llm_nodes:
        llm_id = llm_node.get("id")
        if not isinstance(llm_id, str):
            continue

        incoming_retrieval_edges: list[dict[str, Any]] = []
        for edge in edges:
            source_id = edge.get("source")
            if edge.get("target") != llm_id or not isinstance(source_id, str):
                continue
            source_node = nodes_by_id.get(source_id)
            if source_node and source_node.get("data", {}).get("type") == BuiltinNodeTypes.KNOWLEDGE_RETRIEVAL:
                incoming_retrieval_edges.append(edge)
        retrieval_ids = list(
            dict.fromkeys(edge["source"] for edge in incoming_retrieval_edges if isinstance(edge.get("source"), str))
        )
        if len(retrieval_ids) < 2:
            continue

        llm_data = llm_node.get("data")
        if not isinstance(llm_data, dict):
            continue
        context = llm_data.get("context")
        if not isinstance(context, dict) or not context.get("enabled"):
            continue
        selector = context.get("variable_selector")
        if selector not in [[retrieval_id, "result"] for retrieval_id in retrieval_ids]:
            continue

        template_id = _next_generated_node_id(prefix="retrieval_context", used_ids=used_ids)
        variables = [
            {"variable": f"knowledge_{index}", "value_selector": [retrieval_id, "result"]}
            for index, retrieval_id in enumerate(retrieval_ids, start=1)
        ]
        sections = [
            (
                f"## Knowledge source {index}\n"
                f"{{% for item in knowledge_{index} %}}{{{{ item.content }}}}\n{{% endfor %}}"
            )
            for index in range(1, len(retrieval_ids) + 1)
        ]
        nodes.append(
            {
                "id": template_id,
                "type": "custom",
                "position": {"x": 0, "y": 0},
                "data": {
                    "type": BuiltinNodeTypes.TEMPLATE_TRANSFORM,
                    "title": "Combine Knowledge",
                    "variables": variables,
                    "template": "\n\n".join(sections),
                },
            }
        )

        incoming_edge_objects = {id(edge) for edge in incoming_retrieval_edges}
        edges[:] = [edge for edge in edges if id(edge) not in incoming_edge_objects]
        edges.extend(
            {"source": retrieval_id, "target": template_id, "type": "custom"} for retrieval_id in retrieval_ids
        )
        edges.append({"source": template_id, "target": llm_id, "type": "custom"})

        context["variable_selector"] = [template_id, "output"]
        _ensure_llm_context_placeholder(llm_data)
        logger.info(
            "Workflow generator: inserted template %s to combine retrieval inputs for LLM %s",
            template_id,
            llm_id,
        )


def _next_generated_node_id(*, prefix: str, used_ids: set[str]) -> str:
    """Return a short runtime-safe node id and reserve it in ``used_ids``."""
    suffix = 1
    candidate = prefix
    while candidate in used_ids:
        suffix += 1
        candidate = f"{prefix}_{suffix}"
    used_ids.add(candidate)
    return candidate


def _ensure_llm_context_placeholder(llm_data: dict[str, Any]) -> None:
    """Ensure an enabled LLM context is actually present in its prompt."""
    prompt_template = llm_data.get("prompt_template")
    if isinstance(prompt_template, list):
        messages = [message for message in prompt_template if isinstance(message, dict)]
        if any("{{#context#}}" in str(message.get("text") or "") for message in messages):
            return
        target = next((message for message in reversed(messages) if message.get("role") == "user"), None)
        if target is None:
            prompt_template.append({"role": "user", "text": "{{#context#}}"})
            return
        target["text"] = f"{target.get('text') or ''}\n\n{{{{#context#}}}}"
        return
    if isinstance(prompt_template, dict):
        text = str(prompt_template.get("text") or "")
        if "{{#context#}}" not in text:
            prompt_template["text"] = f"{text}\n\n{{{{#context#}}}}"


def reconcile_references(
    *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], mode: WorkflowGenerationMode
) -> None:
    _insert_multi_retrieval_context_templates(nodes=nodes, edges=edges)
    _unwrap_single_wrapped_selectors(nodes=nodes)
    _normalize_sys_query_references(nodes=nodes, mode=mode)
    _reconcile_variable_references(nodes=nodes, mode=mode)
