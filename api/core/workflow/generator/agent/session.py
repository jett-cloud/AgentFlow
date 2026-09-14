"""Restore an append-only tool-loop session and apply the next user turn.

``restore_session`` rebuilds typed ``AgentMessage`` rows from persisted
``WorkflowAssistMessage`` records (or test doubles with the same attributes).
Malformed rows raise ``InvalidAgentMessageError``; they never become an invented
session. ``apply_user_turn`` either answers a trailing pending ``ask_user`` or
appends a user ``message``. It does not reset history or the candidate graph.
"""

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import replace
from typing import Any, Protocol, cast

from core.workflow.generator.agent.types import (
    AgentMessage,
    AgentMessageEventType,
    AgentMessageRole,
    AgentSession,
    CandidateState,
)
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.types import WorkflowGenerationMode

_EVENT_TYPES = frozenset({"message", "tool_call", "tool_result"})
_ROLES = frozenset({"user", "assistant"})
_ASK_USER = "ask_user"


class InvalidAgentMessageError(ValueError):
    """Raised when a persisted message row cannot be restored into an AgentSession."""


class WorkflowAssistMessageRow(Protocol):
    """Duck-typed ``WorkflowAssistMessage`` row used by ``restore_session``."""

    sequence: int
    event_type: str
    role: str
    status: str
    payload: dict[str, Any]


def restore_session(
    rows: Sequence[WorkflowAssistMessageRow],
    candidate_state: CandidateState,
    generation_mode: WorkflowGenerationMode,
) -> AgentSession:
    """Rebuild an in-memory session from ordered message rows and candidate state.

    Rows are sorted by ``sequence``. Unknown ``event_type`` / ``role`` values,
    a non-dict payload, or a ``tool_call`` / ``tool_result`` missing its id
    raise ``InvalidAgentMessageError`` instead of skipping the row.
    """
    messages = [_message_from_row(row) for row in sorted(rows, key=lambda item: item.sequence)]
    _reject_duplicate_sequences(messages)
    return AgentSession(
        messages=messages,
        candidate_graph=_restore_graph(candidate_state),
        candidate_revision=_optional_int(candidate_state.get("revision"), default=0) or 0,
        candidate_base_hash=_optional_str(candidate_state.get("base_hash")),
        compacted_until_sequence=_optional_int(candidate_state.get("compacted_until_sequence"), default=None),
        compacted_state=_optional_dict(candidate_state.get("compacted_state")),
        generation_mode=generation_mode,
        last_validation=_optional_dict(candidate_state.get("last_validation")),
        contract_protocol_version=_optional_int(candidate_state.get("contract_protocol_version"), default=None),
        workflow_contract=_optional_object_dict(candidate_state.get("workflow_contract")),
        contract_revision=_optional_int(candidate_state.get("contract_revision"), default=0) or 0,
        contract_hash=_optional_str(candidate_state.get("contract_hash")),
    )


def apply_user_turn(
    session: AgentSession,
    text: str,
    references: list[dict[str, Any]] | None = None,
) -> AgentSession:
    """Apply the next user text without resetting the conversation.

    Pending means the last message is a ``tool_call`` with ``status=pending``,
    ``name=ask_user``, and no matching ``tool_result``. That call is marked
    ``completed`` (arguments and earlier text stay as stored) and ``text`` is
    appended as its ``tool_result``. Otherwise ``text`` is a new user message.
    """
    pending = _pending_ask_user(session.messages)
    if pending is None:
        return replace(
            session,
            messages=[*session.messages, _user_message(_next_sequence(session.messages), text, references)],
        )

    completed = replace(pending, status="completed")
    answered = [completed if message.sequence == pending.sequence else message for message in session.messages]
    result = AgentMessage(
        sequence=_next_sequence(answered),
        event_type="tool_result",
        role="assistant",
        status="completed",
        payload={
            "tool_call_id": str(pending.payload["id"]),
            "name": str(pending.payload.get("name") or _ASK_USER),
            "content": text,
        },
    )
    return replace(session, messages=[*answered, result])


def _message_from_row(row: WorkflowAssistMessageRow) -> AgentMessage:
    event_type = row.event_type
    if event_type not in _EVENT_TYPES:
        raise InvalidAgentMessageError(f"Unsupported event_type {event_type!r} at sequence {row.sequence}")
    role = row.role
    if role not in _ROLES:
        raise InvalidAgentMessageError(f"Unsupported role {role!r} at sequence {row.sequence}")
    payload = row.payload
    if not isinstance(payload, dict):
        raise InvalidAgentMessageError(f"Payload must be a dict at sequence {row.sequence}")
    restored = deepcopy(payload)
    if event_type == "tool_call":
        call_id = restored.get("id")
        name = restored.get("name")
        if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
            raise InvalidAgentMessageError(f"tool_call payload requires id and name at sequence {row.sequence}")
    elif event_type == "tool_result":
        tool_call_id = restored.get("tool_call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise InvalidAgentMessageError(f"tool_result payload requires tool_call_id at sequence {row.sequence}")
    return AgentMessage(
        sequence=int(row.sequence),
        event_type=cast(AgentMessageEventType, event_type),
        role=cast(AgentMessageRole, role),
        status=str(row.status),
        payload=restored,
    )


def _reject_duplicate_sequences(messages: list[AgentMessage]) -> None:
    seen: set[int] = set()
    for message in messages:
        if message.sequence in seen:
            raise InvalidAgentMessageError(f"Duplicate message sequence {message.sequence}")
        seen.add(message.sequence)


def _pending_ask_user(messages: list[AgentMessage]) -> AgentMessage | None:
    if not messages:
        return None
    last = messages[-1]
    if last.event_type != "tool_call" or last.status != "pending":
        return None
    if last.payload.get("name") != _ASK_USER:
        return None
    call_id = last.payload.get("id")
    if not isinstance(call_id, str) or not call_id:
        return None
    if any(
        message.event_type == "tool_result" and message.payload.get("tool_call_id") == call_id for message in messages
    ):
        return None
    return last


def _user_message(sequence: int, text: str, references: list[dict[str, Any]] | None = None) -> AgentMessage:
    payload: dict[str, Any] = {"text": text}
    if references:
        payload["references"] = list(references)
    return AgentMessage(
        sequence=sequence,
        event_type="message",
        role="user",
        status="completed",
        payload=payload,
    )


def _next_sequence(messages: list[AgentMessage]) -> int:
    if not messages:
        return 1
    return messages[-1].sequence + 1


def _restore_graph(candidate_state: CandidateState) -> MinimalGraphDict | dict[str, Any] | None:
    graph = candidate_state.get("graph")
    if graph is None:
        return None
    if not isinstance(graph, dict):
        raise InvalidAgentMessageError("candidate_state.graph must be a dict when present")
    return deepcopy(graph)


def _optional_int(value: object, *, default: int | None) -> int | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (str, bytes, bytearray, int, float)):
        raise InvalidAgentMessageError("candidate_state integer fields must be numeric when present")
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_dict(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidAgentMessageError("candidate_state JSON fields must be dicts when present")
    return deepcopy(value)


def _optional_object_dict(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidAgentMessageError("candidate_state.workflow_contract must be a dict when present")
    return deepcopy(value)
