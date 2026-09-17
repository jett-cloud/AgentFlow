"""ToolResult envelopes and the retryable lookup table.

``retryable`` is looked up from ``RETRYABLE_BY_ERROR_CODE``; handlers must not
set it ad hoc. Failures are always a ``ToolResult`` with ``ok=False``, never an
exception. Codes forwarded from ``validate_graph`` (including private-ref
``UNRESOLVED_REFERENCE``) must be in the table so ``error()`` cannot KeyError.
Unknown codes default to retryable so the envelope still forms.
"""

from typing import Any

from core.workflow.generator.agent.types import ToolCall, ToolResult

RETRYABLE_BY_ERROR_CODE: dict[str, bool] = {
    "NODE_NOT_FOUND": True,
    "NODE_EXISTS": True,
    "INVALID_PARENT": True,
    "DUPLICATE_BATCH_NODE_ID": True,
    "DEPENDENCY_ORDER_REQUIRED": True,
    "DEPENDENCY_FAILED": True,
    "MODEL_CALL_BUDGET_EXHAUSTED": True,
    "RUN_ABORTED": False,
    "CONTRACT_PROTOCOL_UNAVAILABLE": False,
    "CONTRACT_REVISION_CONFLICT": True,
    "INVALID_WORKFLOW_PLAN": True,
    "UNKNOWN_REQUIREMENT_TURN": True,
    "INVALID_REQUIREMENT_EVIDENCE": True,
    "PLAN_RESOURCE_UNRESOLVED": True,
    "PLAN_BASE_HASH_MISMATCH": True,
    "EXPLICIT_REQUIREMENT_DROPPED": True,
    "WORKFLOW_PLAN_REQUIRED": True,
    "PLAN_NODE_UNRESOLVED": True,
    "PLAN_EDIT_SCOPE_VIOLATION": True,
    "PLAN_MUTATION_NOT_DECLARED": True,
    "PLAN_MUTATION_MISMATCH": True,
    "WORKFLOW_PLAN_INCOMPLETE": True,
    "AMBIGUOUS_EDGE": True,
    "INVALID_ARGUMENT": True,
    "INVALID_NODE_ID": True,
    "INVALID_SCHEMA": True,
    "INVALID_NODE_CONFIG": True,
    "INTENT_INPUT_MISSING": True,
    "INTENT_OUTPUT_MISSING": True,
    "INTENT_OUTPUT_TYPE_MISMATCH": True,
    "REFERENCE_NOT_AVAILABLE": True,
    "PRIVATE_CONTAINER_REFERENCE": True,
    "UNKNOWN_NODE_REFERENCE": True,
    "TYPE_UNCHANGED_USE_UPDATE": True,
    "UNKNOWN_DATASET": True,
    "UNKNOWN_MODEL": True,
    "UNKNOWN_TOOL": True,
    "TOOL_SCHEMA_UNAVAILABLE": True,
    "UNKNOWN_OUTPUT": True,
    "UNKNOWN_SKILL": True,
    "INVALID_CODE_OUTPUT": True,
    "INVALID_END_OUTPUT": True,
    "INVALID_AGENT_NODE": True,
    "AGENT_BINDING_MISSING": True,
    "VARIABLE_TYPE_MISMATCH": True,
    "TOOL_OUTPUT_SCHEMA_UNAVAILABLE": True,
    "TOOL_NODE_REQUIRES_BUILD_TOOL_NODE": True,
    "AGENT_NODE_REQUIRES_BUILD_AGENT_NODE": True,
    "CONTAINER_REQUIRES_BUILD_LOOP": True,
    "CONTAINER_REQUIRES_BUILD_ITERATION": True,
    "GRAPH_CYCLE": True,
    "INVALID_CONTAINER": True,
    "INVALID_CONTAINER_OUTPUT": True,
    "EXTERNAL_REFERENCE_BROKEN": True,
    "STALE_COMPILE_RESULT": True,
    "NESTED_CONTAINER_UNSUPPORTED": True,
    "UNRESOLVED_REFERENCE": True,
    "DUPLICATE_NODE_ID": True,
    "MISSING_START": True,
    "MISSING_TERMINAL": True,
    "DANGLING_EDGE": True,
    "INVALID_JSON": True,
    "EMPTY_INSTRUCTION": True,
    "INSTRUCTION_TOO_LONG": True,
    "EMPTY_PLAN": True,
    "OUTPUT_TRUNCATED": True,
    "PLANNER_ACTION_LIMIT": True,
    "PLANNER_BUDGET_EXHAUSTED": True,
    "PLANNER_CLARIFICATION_LIMIT": True,
    "PLANNER_NO_PROGRESS": True,
    "PLANNER_CONTEXT_LIMIT": True,
    "PLANNER_REQUIREMENT_INVALID": True,
    "PLANNER_POLICY_DENIED": True,
    "MODEL_ERROR": True,
    "PERMISSION_DENIED": False,
    "RESOURCE_FORBIDDEN": False,
    "UNSUPPORTED_NODE_TYPE": False,
    "CAPABILITY_UNAVAILABLE": False,
    "LIVE_RUN_REQUIRES_CONSENT": True,
}


def retryable(error_code: str) -> bool:
    return RETRYABLE_BY_ERROR_CODE.get(error_code, True)


def ok(call: ToolCall, *, changed: bool, content: dict[str, object]) -> ToolResult:
    return {
        "tool_call_id": call["id"],
        "name": call["name"],
        "ok": True,
        "changed": changed,
        "content": content,
        "error": None,
        "error_code": None,
        "retryable": False,
    }


def error(
    call: ToolCall,
    error_code: str,
    message: str,
    *,
    path: str | None = None,
    child_ref: str | None = None,
    cause: dict[str, object] | None = None,
) -> ToolResult:
    result: dict[str, object] = {
        "tool_call_id": call["id"],
        "name": call["name"],
        "ok": False,
        "changed": False,
        "content": None,
        "error": message,
        "error_code": error_code,
        "retryable": retryable(error_code),
    }
    if path is not None:
        result["path"] = path
    if child_ref is not None:
        result["child_ref"] = child_ref
    if cause is not None:
        result["cause"] = cause
    return result  # type: ignore[return-value]


def require_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if isinstance(value, str) and value:
        return value
    return None
