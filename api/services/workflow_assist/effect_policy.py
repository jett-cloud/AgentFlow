"""Classify candidate nodes for sandbox execution vs metering vs always-simulate.

``local_execute`` may run in any acceptance mode without tenant tool/LLM usage.
``metered`` hits user quota and may run only after live consent.
``simulate_always`` never executes real side effects (HTTP writes, messaging).
"""

from __future__ import annotations

from typing import Literal

from core.workflow.generator.agent.types import AgentSession

EffectClass = Literal["local_execute", "metered", "simulate_always"]

LIVE_CONSENT_QUESTION_ID = "live_run_consent"
_LOCAL_EXECUTE = frozenset({"start", "end", "answer", "code", "if-else", "iteration", "loop"})
_METERED = frozenset({"llm", "knowledge-retrieval", "tool", "agent"})
_AFFIRMATIVE = frozenset(
    {
        "yes",
        "y",
        "true",
        "1",
        "ok",
        "okay",
        "同意",
        "允许",
        "可以",
        "确认",
    }
)


def classify_effect(node_type: str) -> EffectClass:
    """Return the execution class for one node type."""
    if node_type in _LOCAL_EXECUTE:
        return "local_execute"
    if node_type in _METERED:
        return "metered"
    return "simulate_always"


def live_run_authorized_from_session(session: AgentSession) -> bool:
    """True only when this turn just answered ``live_run_consent`` affirmatively.

    A later ordinary user message does not inherit the grant.
    """
    messages = session.messages
    if len(messages) < 2:
        return False
    result = messages[-1]
    call = messages[-2]
    if result.event_type != "tool_result" or call.event_type != "tool_call":
        return False
    if call.payload.get("name") != "ask_user":
        return False
    arguments = call.payload.get("arguments")
    questions = arguments.get("questions") if isinstance(arguments, dict) else None
    if not isinstance(questions, list):
        return False
    if not any(isinstance(item, dict) and item.get("id") == LIVE_CONSENT_QUESTION_ID for item in questions):
        return False
    return _is_affirmative(_answer_text(result.payload.get("content")))


def _answer_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _is_affirmative(text: str) -> bool:
    lowered = text.lower().strip()
    return lowered in _AFFIRMATIVE
