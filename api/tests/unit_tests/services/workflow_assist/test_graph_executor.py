from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.workflow.generator.graph.graph_ops import connect, empty_graph, upsert_node
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from core.workflow.generator.validation.graph_validator import validate_graph
from core.workflow.generator.compiler.node_builder import assemble_graph
from graphon.enums import BuiltinNodeTypes, WorkflowNodeExecutionStatus
from graphon.graph_events import (
    GraphRunAbortedEvent,
    GraphRunFailedEvent,
    GraphRunSucceededEvent,
    NodeRunFailedEvent,
    NodeRunRetryEvent,
    NodeRunSucceededEvent,
)
from graphon.node_events import NodeRunResult
from services.workflow_assist.graph_executor import (
    build_acceptance_graph_executor,
    execute_acceptance_graph,
    failed_traces_from_events,
)
from services.workflow_assist.sandbox import build_acceptance_runner


def _start_end():
    graph = upsert_node(
        empty_graph(), node_id="start", node_type="start", title="开始", desc="", config={"variables": []}
    )
    graph = upsert_node(graph, node_id="end", node_type="end", title="结束", desc="", config={})
    return connect(graph, source="start", target="end")


def _prepared_start_end():
    return postprocess_graph(graph=_start_end(), mode="workflow")


def _prepared_generated_loop():
    graph = assemble_graph(
        plan_nodes=[
            {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start workflow"},
            {"id": "loop", "label": "Loop", "node_type": "loop", "purpose": "Count once"},
            {
                "id": "increment",
                "label": "Increment",
                "node_type": "assigner",
                "purpose": "Increment count",
                "parent": "loop",
            },
            {"id": "end", "label": "End", "node_type": "end", "purpose": "Return count"},
        ],
        plan_edges=[{"source": "start", "target": "loop"}, {"source": "loop", "target": "end"}],
        configs_by_id={
            "start": {"variables": []},
            "loop": {
                "loop_count": 3,
                "break_conditions": [
                    {
                        "id": "done",
                        "variable_selector": ["loop", "count"],
                        "comparison_operator": "≥",
                        "value": "1",
                        "varType": "number",
                    }
                ],
                "logical_operator": "and",
                "loop_variables": [
                    {
                        "id": "count",
                        "label": "count",
                        "value": "0",
                        "value_type": "constant",
                        "var_type": "number",
                    }
                ],
            },
            "increment": {
                "version": "2",
                "items": [
                    {
                        "input_type": "constant",
                        "operation": "+=",
                        "value": 1,
                        "variable_selector": ["loop", "count"],
                        "write_mode": "over-write",
                    }
                ],
            },
            "end": {"outputs": [{"variable": "count", "value_selector": ["loop", "count"], "value_type": "number"}]},
        },
        existing_by_id={},
    )
    return postprocess_graph(graph=graph, mode="workflow")


def _failed_node_event() -> NodeRunFailedEvent:
    return NodeRunFailedEvent(
        id="exec",
        node_id="code",
        node_type=BuiltinNodeTypes.CODE,
        start_at=datetime.now(UTC).replace(tzinfo=None),
        error="sandbox timeout",
        node_run_result=NodeRunResult(status=WorkflowNodeExecutionStatus.FAILED, error="sandbox timeout"),
    )


def test_failed_traces_map_node_failures() -> None:
    traces = failed_traces_from_events([_failed_node_event(), GraphRunFailedEvent(error="graph boom")])
    assert traces == [
        {"id": "code", "type": "code", "error": "Acceptance execution failed (runtime)", "category": "runtime"}
    ]


def test_failed_traces_fall_back_to_graph_error() -> None:
    traces = failed_traces_from_events([GraphRunFailedEvent(error="init exploded")])
    assert traces == [
        {"id": "graph", "type": "graph", "error": "Acceptance execution failed (runtime)", "category": "runtime"}
    ]


def test_failed_traces_preserve_graph_abort_reason() -> None:
    traces = failed_traces_from_events([GraphRunAbortedEvent(reason="user cancelled")])

    assert traces == [
        {"id": "graph", "type": "graph", "error": "Acceptance execution aborted", "category": "runtime"}
    ]


def test_failed_traces_empty_on_success() -> None:
    assert failed_traces_from_events([GraphRunSucceededEvent(outputs={"text": "ok"})]) == []


def test_execution_trace_captures_node_and_terminal_outputs() -> None:
    node_result = NodeRunResult(
        status=WorkflowNodeExecutionStatus.SUCCEEDED,
        outputs={"result": 42},
    )
    traces = failed_traces_from_events(
        [
            NodeRunSucceededEvent(
                id="exec",
                node_id="code",
                node_type=BuiltinNodeTypes.CODE,
                start_at=datetime.now(UTC).replace(tzinfo=None),
                node_run_result=node_result,
            ),
            GraphRunSucceededEvent(outputs={"answer": 42}),
        ]
    )

    assert traces.node_outputs == {"code": {"result": 42}}
    assert traces.graph_outputs == {"answer": 42}


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("provider credential is missing", "credential"),
        ("connection timed out", "network"),
        ("quota exceeded", "quota"),
        ("sandbox timeout", "runtime"),
    ],
)
def test_failed_traces_classify_external_failures(message: str, category: str) -> None:
    event = _failed_node_event()
    event.error = message
    event.node_run_result.error = message

    traces = failed_traces_from_events([event])

    assert traces[0]["category"] == category


def test_failed_traces_redact_secrets_before_evidence() -> None:
    event = _failed_node_event()
    event.error = "Authorization: Bearer secret-token api_key=top-secret"
    event.node_run_result.error = event.error

    traces = failed_traces_from_events([event])

    assert traces[0]["error"] == "Acceptance execution failed (credential)"


def test_incomplete_event_stream_is_not_success() -> None:
    traces = failed_traces_from_events([])
    assert traces[0]["id"] == "graph"


def test_failed_node_is_recorded_in_observed_coverage() -> None:
    traces = failed_traces_from_events([_failed_node_event()])
    assert traces.executed_node_ids == {"code"}


def test_retry_then_success_is_successful_and_records_observed_coverage() -> None:
    retry = NodeRunRetryEvent(
        id="exec",
        node_id="code",
        node_type=BuiltinNodeTypes.CODE,
        node_title="Code",
        start_at=datetime.now(UTC).replace(tzinfo=None),
        error="sandbox busy",
        retry_index=1,
    )

    traces = failed_traces_from_events([retry, GraphRunSucceededEvent(outputs={})])

    assert traces == []
    assert traces.executed_node_ids == {"code"}


def test_execute_acceptance_graph_runs_start_end() -> None:
    traces = execute_acceptance_graph(
        _prepared_start_end(),
        tenant_id="tenant",
        app_id="app",
        user_id="user",
        mode="simulated",
    )
    assert traces == []


def test_execute_acceptance_graph_runs_generated_loop_through_real_engine() -> None:
    graph = _prepared_generated_loop()
    assert validate_graph(graph=graph, mode="workflow") == []

    traces = execute_acceptance_graph(
        graph,
        tenant_id="tenant",
        app_id="app",
        user_id="user",
        mode="simulated",
    )

    assert traces == []
    assert {"start", "loop", "increment", "end"}.issubset(traces.executed_node_ids)


def test_execute_acceptance_graph_uses_draft_workflow_id(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _capture(graph, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("services.workflow_assist.graph_executor._build_acceptance_engine", _capture)
    monkeypatch.setattr(
        "services.workflow_assist.graph_executor.iter_dify_graph_engine_events",
        lambda engine: iter([GraphRunSucceededEvent(outputs={})]),
    )
    traces = execute_acceptance_graph(
        _start_end(),
        tenant_id="tenant",
        app_id="app",
        user_id="user",
        mode="live",
        workflow_id="draft-workflow",
    )
    assert traces == []
    assert captured["workflow_id"] == "draft-workflow"


def test_execute_acceptance_graph_maps_engine_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.workflow_assist.graph_executor._build_acceptance_engine",
        lambda graph, **kwargs: MagicMock(),
    )
    monkeypatch.setattr(
        "services.workflow_assist.graph_executor.iter_dify_graph_engine_events",
        lambda engine: iter([_failed_node_event(), GraphRunFailedEvent(error="boom")]),
    )
    traces = execute_acceptance_graph(
        _start_end(),
        tenant_id="tenant",
        app_id="app",
        user_id="user",
        mode="simulated",
    )
    assert traces[0]["id"] == "code"
    assert traces[0]["error"] == "Acceptance execution failed (runtime)"


def test_execute_acceptance_graph_does_not_attach_persistence(monkeypatch) -> None:
    imported: list[str] = []

    def _boom(*_args, **_kwargs):
        imported.append("WorkflowPersistenceLayer")
        raise AssertionError("acceptance must not persist WorkflowRun rows")

    monkeypatch.setattr(
        "core.app.workflow.layers.persistence.WorkflowPersistenceLayer",
        _boom,
        raising=False,
    )
    traces = execute_acceptance_graph(
        _prepared_start_end(),
        tenant_id="tenant",
        app_id="app",
        user_id="user",
        mode="simulated",
    )
    assert imported == []
    assert traces == []


def test_build_acceptance_runner_injects_executor() -> None:
    runner = build_acceptance_runner(tenant_id="t", app_id="a", user_id="u")
    assert runner._execute_graph is not None
    assert build_acceptance_graph_executor(tenant_id="t", app_id="a", user_id="u") is not None
