"""Scripted Workflow Assist eval harness. No live LLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.workflow.generator.agent.graph_ops import empty_graph
from core.workflow.generator.agent.loop import iter_agent_events
from core.workflow.generator.agent.tools import ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.agent.types import AgentMessage, AgentSession, MinimalGraphDict
from core.workflow.generator.llm_response import LLMJsonClient
from core.workflow.generator.node_builder import BuilderInput

CASES_DIR = Path(__file__).resolve().parent / "cases"


class FakeInvoker:
    def __init__(self, turns: list[list[dict[str, Any]]]) -> None:
        self._queue = [{"tool_calls": turn} for turn in turns]
        self.invoke_count = 0

    def invoke(self, messages: object = None, **kwargs: object) -> dict[str, Any]:
        self.invoke_count += 1
        if not self._queue:
            return {"text": ""}
        return self._queue.pop(0)


class FakeCancellation:
    def reason(self) -> str | None:
        return None


class FakeLimits:
    def __init__(self) -> None:
        self.max_model_calls = 16


class ScriptedAcceptanceRunner:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls = 0

    def run(self, *, graph, revision, graph_hash, case_ids, mode):
        self.calls += 1
        passed = not (self.fail_first and self.calls == 1)
        return [
            {
                "attempt_id": f"att-{self.calls}",
                "revision": revision,
                "graph_hash": graph_hash,
                "case_id": (case_ids or ["default"])[0],
                "passed": passed,
                "status": "simulated",
                "failed_nodes": [] if passed else [{"id": "end", "type": "end", "error": "missing output"}],
                "evidence": [],
                "trace_summary": "ok" if passed else "missing output",
                "unverified_nodes": [],
            }
        ]


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_path"] = path.name
        cases.append(payload)
    return cases


def _builder_input(instruction: str) -> BuilderInput:
    return BuilderInput(
        provider="openai",
        model_name="gpt-4o",
        model_mode="chat",
        mode="workflow",
        instruction=instruction,
        ideal_output="",
        plan_nodes=[],
        plan_edges=[],
        tool_catalogue_text="",
        knowledge_catalogue_text="",
        start_inputs=[],
        current_graph=None,
        output_language="zh-Hans",
    )


def run_case(case: dict[str, Any], *, build_node_config: dict[str, Any] | None = None) -> dict[str, Any]:
    instruction = str(case.get("instruction") or "")
    initial = case.get("initial_graph")
    graph: MinimalGraphDict = empty_graph() if initial is None else initial
    context = ToolContext(
        env=ToolEnv(
            tenant_id="tenant-1",
            mode="workflow",
            tool_entries=[],
            knowledge_entries=[],
            installed_tools=set(),
            installed_dataset_ids=set(case.get("installed_dataset_ids") or []),
            knowledge_available=True,
            tools_available=True,
            builder_input=_builder_input(instruction),
            llm_client=LLMJsonClient(model_instance=object(), model_parameters={}),  # type: ignore[arg-type]
            acceptance_runner=ScriptedAcceptanceRunner(fail_first=bool(case.get("fake_acceptance_fail_first"))),
            live_run_authorized=bool(case.get("live_run_authorized")),
        ),
        state=ToolTurnState(graph=graph, candidate_revision=0),
    )
    session = AgentSession(
        messages=[
            AgentMessage(
                sequence=1,
                event_type="message",
                role="user",
                status="completed",
                payload={"text": instruction},
            )
        ],
        candidate_graph=graph,
        candidate_revision=0,
        candidate_base_hash=None,
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
        edit_mode="rebuild",
    )
    invoker = FakeInvoker(list(case.get("queued_tool_calls") or []))
    events = list(
        iter_agent_events(
            session,
            context,
            invoker,
            FakeCancellation(),
            FakeLimits(),
        )
    )
    names = [name for name, _ in events]
    node_types = [
        str(node.get("data", {}).get("type") or "")
        for node in (session.candidate_graph or {}).get("nodes") or []
        if isinstance(node, dict)
    ]
    finish_payloads = [payload for name, payload in events if name == "tool_result" and payload.get("name") == "finish"]
    saw_no_evidence = any(
        isinstance(payload.get("summary"), str) and "NO_EVIDENCE" in str(payload)
        for payload in finish_payloads
    )
    if not saw_no_evidence:
        saw_no_evidence = any(
            isinstance(item.payload.get("content"), dict)
            and (item.payload.get("content") or {}).get("acceptance", {}).get("reason") == "NO_EVIDENCE"
            for item in session.messages
            if item.event_type == "tool_result" and item.payload.get("name") == "finish"
        )
    live_blocked = any(
        item.payload.get("error_code") == "LIVE_RUN_REQUIRES_CONSENT" for item in session.messages
    )
    terminal = names[-1] if names else "none"
    return {
        "terminal": terminal,
        "names": names,
        "node_types": node_types,
        "node_ids": [
            str(node.get("id") or "")
            for node in (session.candidate_graph or {}).get("nodes") or []
            if isinstance(node, dict)
        ],
        "saw_no_evidence": saw_no_evidence,
        "live_blocked": live_blocked,
        "handles": [
            str(edge.get("sourceHandle") or "")
            for edge in (session.candidate_graph or {}).get("edges") or []
            if isinstance(edge, dict)
        ],
        "parents": {
            str(node.get("id")): str(node.get("parentId") or "")
            for node in (session.candidate_graph or {}).get("nodes") or []
            if isinstance(node, dict)
        },
    }
