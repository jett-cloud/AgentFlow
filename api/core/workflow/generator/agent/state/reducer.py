"""state.reducer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.workflow.generator.agent.tools.tools import (
    ToolContext,
    dispatch,
)
from core.workflow.generator.agent.types import (
    AgentEvent,
    AgentMessage,
    AgentMessageEventType,
    AgentMessageRole,
    AgentSession,
    ToolCall,
    ToolResult,
)
from core.workflow.generator.graph.types import MinimalGraphDict


def _append_assistant_prose(
    session: AgentSession,
    *,
    text: str | None,
    reasoning: str | None,
    message_id: object | None = None,
) -> None:
    payload: dict[str, Any] = {"text": text or ""}
    if isinstance(reasoning, str) and reasoning:
        payload["reasoning"] = reasoning
    if isinstance(message_id, str) and message_id:
        payload["message_id"] = message_id
    _append(
        session,
        event_type="message",
        role="assistant",
        status="completed",
        payload=payload,
    )


def _run_tool(
    session: AgentSession,
    context: ToolContext,
    call: ToolCall,
    start_graph: MinimalGraphDict,
) -> tuple[list[AgentEvent], bool, ToolResult]:
    result = dispatch(call, context)
    _apply_revision(session, context, call["name"], result)
    tool_call_event: AgentEvent = (
        "tool_call",
        {"id": call["id"], "name": call["name"], "arguments": call["arguments"]},
    )

    if call["name"] == "ask_user" and result["ok"]:
        _append(
            session,
            event_type="tool_call",
            role="assistant",
            status="pending",
            payload={"id": call["id"], "name": call["name"], "arguments": call["arguments"]},
        )
        questions = _questions(result, call)
        waiting: AgentEvent = ("waiting_user", {"tool_call_id": call["id"], "questions": questions})
        return [tool_call_event, waiting], True, result

    _append(
        session,
        event_type="tool_call",
        role="assistant",
        status="completed",
        payload={"id": call["id"], "name": call["name"], "arguments": call["arguments"]},
    )
    _append(
        session,
        event_type="tool_result",
        role="assistant",
        status="completed",
        payload=_result_row(result),
    )
    events: list[AgentEvent] = [tool_call_event, ("tool_result", _result_event(result, context))]

    if call["name"] == "fail" and result["ok"]:
        reason = ""
        if isinstance(result["content"], dict):
            value = result["content"].get("reason")
            reason = value if isinstance(value, str) else ""
        if not reason:
            fallback = call["arguments"].get("reason")
            reason = fallback if isinstance(fallback, str) else ""
        events.append(("failed", {"reason": reason}))
        return events, True, result
    if call["name"] == "finish" and result["ok"]:
        events.append(("done", _done_payload(result, context, start_graph, call)))
        return events, True, result
    return events, False, result


def _apply_revision(session: AgentSession, context: ToolContext, name: str, result: ToolResult) -> None:
    session.workflow_contract = deepcopy(context.state.workflow_contract)
    session.contract_revision = context.state.contract_revision
    session.contract_hash = context.state.contract_hash
    if name == "submit_workflow_plan" and result["ok"]:
        session.last_acceptance = None
    if name in {"finish", "run_acceptance"}:
        session.candidate_revision = context.state.candidate_revision
        session.candidate_graph = context.state.graph
        _remember_validation(session, context, name, result)
        _remember_acceptance(session, context, name, result)
        return
    if result["changed"]:
        session.candidate_revision += 1
        context.state.candidate_revision = session.candidate_revision
        session.candidate_graph = context.state.graph
    _remember_validation(session, context, name, result)
    _remember_acceptance(session, context, name, result)


def _remember_validation(session: AgentSession, context: ToolContext, name: str, result: ToolResult) -> None:
    content = result.get("content")
    if name not in {"finish", "validate_graph"} or not isinstance(content, dict) or "valid" not in content:
        return
    session.last_validation = {
        "valid": content.get("valid"),
        "validated_revision": context.state.last_validation_revision,
        "errors": content.get("errors"),
    }


def _remember_acceptance(session: AgentSession, context: ToolContext, name: str, result: ToolResult) -> None:
    content = result.get("content")
    if name == "run_acceptance" and result.get("error_code") == "LIVE_RUN_REQUIRES_CONSENT":
        session.last_acceptance = {
            "passed": None,
            "reason": "LIVE_RUN_REQUIRES_CONSENT",
            "revision": context.state.candidate_revision,
        }
        return
    if name == "run_acceptance" and isinstance(content, dict) and "passed" in content:
        session.last_acceptance = {
            "passed": content.get("passed"),
            "executed": content.get("executed"),
            "revision": context.state.candidate_revision,
            "reason": None,
            "failed_nodes": content.get("failed_nodes") or [],
            "attempt_id": content.get("attempt_id"),
        }
        return
    if name == "finish" and isinstance(content, dict):
        acceptance = content.get("acceptance")
        if isinstance(acceptance, dict) and acceptance.get("reason"):
            session.last_acceptance = {
                "passed": False,
                "revision": context.state.candidate_revision,
                "reason": acceptance.get("reason"),
                "failed_nodes": acceptance.get("failed_nodes") or [],
                "attempt_id": acceptance.get("attempt_id"),
            }


def _questions(result: ToolResult, call: ToolCall) -> object:
    content = result.get("content")
    if isinstance(content, dict) and "questions" in content:
        return content["questions"]
    return call["arguments"].get("questions") or []


def _result_row(result: ToolResult) -> dict[str, Any]:
    row: dict[str, Any] = {
        "tool_call_id": result["tool_call_id"],
        "name": result["name"],
        "ok": result["ok"],
        "changed": result["changed"],
        "content": result["content"],
        "error": result["error"],
        "error_code": result["error_code"],
        "retryable": result["retryable"],
    }
    for key in ("path", "child_ref", "cause"):
        if key in result:
            row[key] = result[key]
    return row


def _result_event(result: ToolResult, context: ToolContext) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": result["tool_call_id"],
        "name": result["name"],
        "ok": result["ok"],
        "summary": _summary(result),
    }
    content = result.get("content")
    if isinstance(content, dict):
        failed_nodes = content.get("failed_nodes")
        if isinstance(failed_nodes, list) and failed_nodes:
            payload["failed_nodes"] = failed_nodes
        acceptance = content.get("acceptance")
        if isinstance(acceptance, dict):
            payload["acceptance"] = acceptance
            nested = acceptance.get("failed_nodes")
            if isinstance(nested, list) and nested:
                payload["failed_nodes"] = nested
    if result["changed"]:
        payload["graph"] = context.state.graph
    return payload


def _summary(result: ToolResult) -> str:
    content = result.get("content")
    if isinstance(content, dict):
        acceptance = content.get("acceptance")
        if isinstance(acceptance, dict):
            reason = acceptance.get("reason")
            if isinstance(reason, str) and reason:
                nodes = acceptance.get("failed_nodes")
                if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict):
                    node_id = nodes[0].get("id") or "?"
                    error = nodes[0].get("error") or ""
                    return f"{reason} {node_id}:{error}".strip()
                return reason
        if content.get("passed") is False:
            trace = content.get("trace_summary")
            if isinstance(trace, str) and trace:
                return trace
            nodes = content.get("failed_nodes")
            count = len(nodes) if isinstance(nodes, list) else 0
            return f"{count} acceptance failures"
        summary = content.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        reason = content.get("reason")
        if isinstance(reason, str) and reason:
            return reason
        if content.get("valid") is False:
            errors = content.get("errors")
            count = len(errors) if isinstance(errors, list) else 0
            return f"{count} validation errors"
    error = result.get("error")
    if isinstance(error, str) and error:
        return error
    return "" if result["ok"] else "error"


def _done_payload(
    result: ToolResult,
    context: ToolContext,
    start_graph: MinimalGraphDict,
    call: ToolCall,
) -> dict[str, Any]:
    content = result["content"] if isinstance(result["content"], dict) else {}
    summary = content.get("summary")
    if not isinstance(summary, str):
        raw = call["arguments"].get("summary")
        summary = raw if isinstance(raw, str) else ""
    errors = content.get("errors")
    return {
        "graph": context.state.graph,
        "summary": summary,
        "diff": _graph_diff(start_graph, context.state.graph),
        "validation": {"ok": bool(content.get("valid")), "errors": errors if isinstance(errors, list) else []},
    }


def _graph_diff(before: MinimalGraphDict, after: MinimalGraphDict) -> dict[str, list[str]]:
    before_nodes = _nodes_by_id(before)
    after_nodes = _nodes_by_id(after)
    added = sorted(node_id for node_id in after_nodes if node_id not in before_nodes)
    removed = sorted(node_id for node_id in before_nodes if node_id not in after_nodes)
    updated = sorted(
        node_id for node_id in after_nodes if node_id in before_nodes and after_nodes[node_id] != before_nodes[node_id]
    )
    return {"added": added, "removed": removed, "updated": updated}


def _nodes_by_id(graph: MinimalGraphDict) -> dict[str, object]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list):
        return {}
    by_id: dict[str, object] = {}
    for node in nodes:
        if isinstance(node, dict):
            node_id = node.get("id")
            if isinstance(node_id, str) and node_id:
                by_id[node_id] = node
    return by_id


def _append(
    session: AgentSession,
    *,
    event_type: AgentMessageEventType,
    role: AgentMessageRole,
    status: str,
    payload: dict[str, Any],
) -> None:
    sequence = session.messages[-1].sequence + 1 if session.messages else 1
    session.messages.append(
        AgentMessage(
            sequence=sequence,
            event_type=event_type,
            role=role,
            status=status,
            payload=payload,
        )
    )
