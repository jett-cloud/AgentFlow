"""System prefix and per-invoke CurrentSituation for the workflow agent.

``render_current_situation`` is a live workspace sketch: mode, revision, and
candidate topology (id / type / title / parent / edges). It is computed for the
prompt copy only, never persisted, and always appended at the tail so the
stable prefix can stay in cache. Node config, full graph JSON, and the tenant
catalogue do not belong here — those are ``read_node`` / ``read_graph`` /
search observations. ``last_finish`` is accepted ``finish.ok`` only;
``validate_graph`` updates ``last_validation`` and must not light ``last_finish``.

Playbook bodies are a second tail message after CurrentSituation. Selection is
heuristic (one skill per turn); the JSON tool schemas stay the action contract.
"""

from core.workflow.generator.agent.types import AgentMessage, AgentSession, MinimalGraphDict
from core.workflow.generator.prompts.loader import PLAYBOOK_SKILLS, read_prompt

_ASK_USER = "ask_user"
_PLAYBOOK_CREATE = "create-from-scratch"
_PLAYBOOK_REPAIR = "repair-validation"
_PLAYBOOK_BIND = "bind-resources"
_PLAYBOOK_EDIT = "edit-local-node"


def select_playbook(session: AgentSession) -> str:
    """Pick one playbook for this turn. Later rules in the table win only if earlier ones miss.

    Priority: bound resources, then failed validation or failed acceptance, then local edit, else create.
    ``edit_mode=local`` on an empty candidate still counts as create.
    """
    if session.referenced_tools or session.referenced_datasets:
        return _PLAYBOOK_BIND
    validation = session.last_validation
    if isinstance(validation, dict) and validation.get("valid") is False:
        return _PLAYBOOK_REPAIR
    acceptance = session.last_acceptance
    if isinstance(acceptance, dict) and acceptance.get("passed") is False:
        return _PLAYBOOK_REPAIR
    graph = session.candidate_graph if isinstance(session.candidate_graph, dict) else None
    nodes = graph.get("nodes") if graph is not None else None
    has_nodes = isinstance(nodes, list) and any(isinstance(node, dict) and node.get("id") for node in nodes)
    if session.selected_node or (session.edit_mode == "local" and has_nodes):
        return _PLAYBOOK_EDIT
    return _PLAYBOOK_CREATE


def render_active_skill(name: str) -> str:
    """Render one playbook body for the prompt tail. Unknown names yield ``""``."""
    if name not in PLAYBOOK_SKILLS:
        return ""
    body = read_prompt(f"agent/skills/{name}/SKILL.md").rstrip()
    if not body:
        return ""
    return f"# Active playbook: {name}\n\n{body}\n"


def render_current_situation(
    session: AgentSession,
    *,
    edit_mode: str | None = None,
    last_run: str | None = None,
    canvas_graph: dict[str, object] | None = None,
    canvas_hash: str | None = None,
) -> str:
    """Render topology and situation metadata from ``session``.

    Request-scoped fields may be passed as kwargs or read from ``AgentSession``
    (``edit_mode``, ``last_run``, ``canvas_graph``, ``canvas_hash``). No node
    config and no catalogue text.
    """
    pending = _pending_ask_user(session.messages)
    resolved_edit = edit_mode or session.edit_mode or "local"
    resolved_last_run = last_run if last_run is not None else session.last_run
    resolved_canvas = canvas_graph if canvas_graph is not None else session.canvas_graph
    resolved_hash = canvas_hash if canvas_hash is not None else session.canvas_hash
    lines = [
        "# Current situation",
        f"mode: {session.generation_mode}",
        f"edit_mode: {resolved_edit}",
        f"phase: {'waiting_user' if pending is not None else 'idle'}",
        f"pending_ask_user: {_pending_ask_user_label(pending)}",
        f"last_run: {_last_run_label(resolved_last_run)}",
        f"last_finish: {_last_finish_label(session)}",
        f"candidate_revision: {session.candidate_revision}",
        f"candidate_base_hash: {session.candidate_base_hash or 'none'}",
        f"last_validation: {_last_validation_label(session)}",
        f"last_acceptance: {_last_acceptance_label(session)}",
        f"apply_status: {_apply_status(session, resolved_canvas, resolved_hash)}",
        f"canvas: {_canvas_label(resolved_canvas)}",
        f"canvas_hash: {resolved_hash or 'not provided'}",
    ]
    if session.selected_node:
        lines.append(f"selected_node: {session.selected_node}")
    if session.referenced_nodes:
        lines.append(f"referenced_nodes: {_format_references(session.referenced_nodes)}")
    if session.referenced_tools:
        lines.append(f"referenced_tools: {_format_references(session.referenced_tools)}")
    if session.referenced_datasets:
        lines.append(f"referenced_datasets: {_format_references(session.referenced_datasets)}")
    graph = session.candidate_graph
    lines.extend(_candidate_sketch(graph if isinstance(graph, dict) else None))
    return "\n".join(lines)


def _pending_ask_user(messages: list[AgentMessage]) -> AgentMessage | None:
    if not messages:
        return None
    last = messages[-1]
    if last.event_type != "tool_call" or last.status != "pending":
        return None
    if last.payload.get("name") != _ASK_USER:
        return None
    return last


def _pending_ask_user_label(pending: AgentMessage | None) -> str:
    if pending is None:
        return "none"
    call_id = pending.payload.get("id")
    return str(call_id) if isinstance(call_id, str) and call_id else "pending"


def _last_validation_label(session: AgentSession) -> str:
    payload = session.last_validation
    if not payload:
        return "none"
    valid = payload.get("valid")
    revision = payload.get("validated_revision")
    if valid is True and revision == session.candidate_revision:
        return f"ok @{revision}"
    if revision is not None and revision != session.candidate_revision:
        prior = "ok" if valid is True else "errors"
        return f"stale ({prior} @{revision}, candidate @{session.candidate_revision})"
    if valid is False:
        codes = _validation_error_codes(payload)
        if revision is None:
            return f"{len(codes)} errors ({', '.join(codes)})" if codes else "errors"
        return f"{len(codes)} errors @{revision} ({', '.join(codes)})"
    return "none"


def _last_acceptance_label(session: AgentSession) -> str:
    payload = session.last_acceptance
    if not payload:
        return "none"
    if payload.get("reason") == "LIVE_RUN_REQUIRES_CONSENT":
        return "LIVE_RUN_REQUIRES_CONSENT"
    passed = payload.get("passed")
    revision = payload.get("revision")
    if passed is True:
        return f"ok @{revision}" if revision is not None else "ok"
    if passed is False:
        nodes = payload.get("failed_nodes")
        parts: list[str] = []
        if isinstance(nodes, list):
            for item in nodes:
                if not isinstance(item, dict):
                    continue
                node_id = item.get("id") or "?"
                error = item.get("error") or item.get("type") or "?"
                parts.append(f"{node_id}:{error}")
        reason = payload.get("reason")
        prefix = f"{len(parts)} failed"
        if revision is not None:
            prefix = f"{prefix} @{revision}"
        if reason:
            prefix = f"{prefix} ({reason})"
        if parts:
            return f"{prefix} ({', '.join(parts)})"
        return prefix
    return "none"


def _validation_error_codes(payload: dict[str, object]) -> list[str]:
    raw_errors = payload.get("errors")
    if not isinstance(raw_errors, list):
        return []
    codes: list[str] = []
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        code = item.get("code") or "?"
        node_id = item.get("node_id") or ""
        codes.append(f"{code}@{node_id}")
    return codes


def _last_run_label(last_run: str | None) -> str:
    if not last_run:
        return "none"
    if last_run in {"done", "failed", "waiting_user", "none", "turn_complete"}:
        return last_run
    return f"aborted ({last_run})"


def _last_finish_label(session: AgentSession) -> str:
    """Accepted ``finish.ok`` only. A passing ``validate_graph`` stays ``none``."""
    for message in reversed(session.messages):
        if message.event_type != "tool_result":
            continue
        name = message.payload.get("name")
        if name == "finish" and message.payload.get("ok") is True:
            return "success (not applied)"
        if message.payload.get("changed") is True:
            return "none"
    return "none"


def _canvas_label(canvas_graph: dict[str, object] | None) -> str:
    if canvas_graph is None:
        return "not provided"
    nodes = canvas_graph.get("nodes") if isinstance(canvas_graph, dict) else None
    edges = canvas_graph.get("edges") if isinstance(canvas_graph, dict) else None
    node_count = len(nodes) if isinstance(nodes, list) else 0
    edge_count = len(edges) if isinstance(edges, list) else 0
    return f"{node_count} nodes, {edge_count} edges"


def _format_references(items: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        label = str(item.get("label") or "").strip()
        parts.append(f"{item_id} ({label})" if label else item_id)
    return ", ".join(parts)


def _topology_key(graph: dict[str, object] | None) -> tuple[frozenset[str], frozenset[tuple[str, str, str]]]:
    if not isinstance(graph, dict):
        return frozenset(), frozenset()
    nodes = graph.get("nodes")
    node_ids = frozenset(
        str(node["id"]) for node in nodes or [] if isinstance(node, dict) and node.get("id") is not None
    )
    edges = graph.get("edges")
    edge_keys: set[tuple[str, str, str]] = set()
    if isinstance(edges, list):
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = edge.get("source")
            target = edge.get("target")
            if isinstance(source, str) and isinstance(target, str):
                handle = edge.get("sourceHandle")
                edge_keys.add((source, target, handle if isinstance(handle, str) else ""))
    return node_ids, frozenset(edge_keys)


def _apply_status(
    session: AgentSession,
    canvas_graph: dict[str, object] | None = None,
    canvas_hash: str | None = None,
) -> str:
    if canvas_hash is not None and session.candidate_base_hash and canvas_hash != session.candidate_base_hash:
        return "canvas changed since candidate base"
    candidate = session.candidate_graph if isinstance(session.candidate_graph, dict) else None
    candidate_empty = not candidate or not candidate.get("nodes")
    if canvas_graph is None:
        return "empty" if candidate_empty else "unknown"
    canvas_empty = not canvas_graph.get("nodes")
    if candidate_empty and canvas_empty:
        return "empty"
    if _topology_key(candidate) == _topology_key(canvas_graph):
        return "in sync"
    return "candidate differs from canvas"


def _candidate_sketch(graph: MinimalGraphDict | dict[str, object] | None) -> list[str]:
    if graph is None:
        return ["candidate:"]
    lines = ["candidate:"]
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id:
                continue
            data = node.get("data")
            data_dict = data if isinstance(data, dict) else {}
            node_type = str(data_dict.get("type") or "")
            title = str(data_dict.get("title") or "")
            sketch = f"- id={node_id!r} type={node_type!r} title={title!r}"
            parent = node.get("parentId") or data_dict.get("parentId")
            if isinstance(parent, str) and parent:
                sketch += f" parent={parent!r}"
            lines.append(sketch)
    edges = graph.get("edges")
    if isinstance(edges, list) and edges:
        lines.append("edges:")
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = edge.get("source")
            target = edge.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            handle = edge.get("sourceHandle")
            if isinstance(handle, str) and handle:
                lines.append(f"- {source} -> {target} (source_handle={handle!r})")
            else:
                lines.append(f"- {source} -> {target}")
    return lines
