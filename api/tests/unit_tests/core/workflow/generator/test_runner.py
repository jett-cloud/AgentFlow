"""Facade and end-to-end orchestration tests for ``WorkflowGenerator``.

Focused module behavior lives beside the module it exercises.
"""

from core.workflow.generator.model_io.llm_response import StageJSONError
from core.workflow.generator.pipeline.runner import _stage_error_to_envelope_code
from graphon.model_runtime.errors.invoke import InvokeError

from ._runner_test_support import (
    MagicMock,
    WorkflowGenerator,
    _GraphFixtureModel,
    _llm_result,
    _stream_builder_json,
    _stream_planner_json,
    json,
    pytest,
)


class TestWorkflowGeneratorWorkflowMode:
    """Generation in plain ``workflow`` mode: start → llm → end."""

    @pytest.fixture
    def planner_response(self) -> str:
        return json.dumps(
            {
                "title": "URL Summarizer",
                "description": "Fetch a URL, summarize it, return the summary.",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "User submits URL."},
                    {"label": "Summarize", "node_type": "llm", "purpose": "Summarize the page."},
                    {"label": "End", "node_type": "end", "purpose": "Return summary."},
                ],
            }
        )

    @pytest.fixture
    def builder_response(self) -> str:
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start", "desc": "", "variables": []},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "llm",
                            "title": "Summarize",
                            "desc": "",
                            "model": {
                                "provider": "openai",
                                "name": "gpt-4o",
                                "mode": "chat",
                                "completion_params": {},
                            },
                            "prompt_template": [
                                {"role": "system", "text": "You summarize URLs."},
                                {"role": "user", "text": "{{#node1.url#}}"},
                            ],
                        },
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "end",
                            "title": "End",
                            "desc": "",
                            "outputs": [{"variable": "summary", "value_selector": ["node2", "text"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "x", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "x", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_happy_path_returns_valid_graph(self, planner_response, builder_response):
        model_instance = _GraphFixtureModel(planner_response, builder_response)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={"temperature": 0.7},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        assert result["error"] == ""
        graph = result["graph"]
        node_types = [n["data"]["type"] for n in graph["nodes"]]
        assert node_types == ["start", "llm", "end"]

        # Postprocessor must lay nodes out left-to-right.
        xs = [n["position"]["x"] for n in graph["nodes"]]
        assert xs == sorted(xs)
        assert len(set(xs)) == len(xs)

        # Edges must be deduped and given a stable id.
        assert len(graph["edges"]) == 2
        ids = [e["id"] for e in graph["edges"]]
        assert len(set(ids)) == 2

        # Edge data.sourceType / targetType must be populated from node lookup.
        first_edge = graph["edges"][0]
        assert first_edge["data"]["sourceType"] == "start"
        assert first_edge["data"]["targetType"] == "llm"

        # Viewport must be float-coerced.
        assert isinstance(graph["viewport"]["zoom"], float)

    def test_missing_end_node_returns_error(self, planner_response):
        planner_payload = json.loads(planner_response)
        planner_payload["nodes"] = planner_payload["nodes"][:-1]
        planner_response = json.dumps(planner_payload)
        builder_response = json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start"},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "llm", "title": "Summarize"},
                    },
                ],
                "edges": [{"id": "x", "source": "node1", "target": "node2", "type": "custom"}],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(planner_response, builder_response)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        assert "end" in result["error"].lower()


class TestWorkflowGeneratorAdvancedChatMode:
    """Generation in ``advanced-chat`` mode terminates with an ``answer`` node."""

    def test_happy_path_terminates_with_answer(self):
        planner = json.dumps(
            {
                "title": "Greeting Bot",
                "description": "Echo greeting.",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "Receive query."},
                    {"label": "Reply", "node_type": "answer", "purpose": "Reply to user."},
                ],
            }
        )
        builder = json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start"},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "answer", "title": "Reply", "answer": "Hi!"},
                    },
                ],
                "edges": [{"id": "x", "source": "node1", "target": "node2", "type": "custom"}],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(planner, builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="advanced-chat",
            instruction="Greet me",
        )

        assert result["error"] == ""
        types = [n["data"]["type"] for n in result["graph"]["nodes"]]
        assert types == ["start", "answer"]

    def test_advanced_chat_missing_answer_returns_error(self):
        # Plan + build both end with an `end` node — invalid in advanced-chat mode.
        planner = json.dumps(
            {
                "title": "Bad bot",
                "description": "wrong terminal",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )
        builder = json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start"},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End"},
                    },
                ],
                "edges": [{"id": "x", "source": "node1", "target": "node2", "type": "custom"}],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(planner, builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="advanced-chat",
            instruction="x",
        )

        assert "answer" in result["error"].lower()


class TestWorkflowGeneratorFailurePaths:
    """Planner / builder failures must return an error envelope, never raise."""

    def test_missing_result_event_falls_back_to_stamped_empty_envelope(self, monkeypatch):
        # Guards the defensive fallback for a future refactor that forgets to
        # emit the final result event — the envelope must still carry a
        # concrete mode, never the ``auto`` sentinel.
        monkeypatch.setattr(WorkflowGenerator, "_iter_generation_events", MagicMock(return_value=iter([])))

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=MagicMock(),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="auto",
            instruction="x",
        )

        assert result["graph"]["nodes"] == []
        assert result["mode"] == "advanced-chat"

    def test_planner_returns_invalid_json(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result("not json at all")

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["error"]
        assert result["graph"]["nodes"] == []

    def test_builder_raises_invoke_error(self):
        planner = json.dumps(
            {
                "title": "x",
                "description": "x",
                "nodes": [
                    {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                    {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
                ],
                "edges": [{"source": "node1", "target": "node2"}],
            }
        )
        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = [
            _llm_result(planner),
            RuntimeError("provider exploded"),
            RuntimeError("provider exploded"),
        ]

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert "provider exploded" in result["error"]

    def test_edge_references_unknown_node(self):
        planner = json.dumps(
            {
                "title": "x",
                "description": "x",
                "nodes": [
                    {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                    {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
                ],
                "edges": [{"source": "node1", "target": "ghost"}],
            }
        )
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result(planner)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert "ghost" in result["error"]


class TestWorkflowGeneratorStream:
    """``generate_workflow_graph_stream`` yields status, ``plan``, status, then ``result``."""

    def test_stream_first_event_is_planning_status(self):
        model_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="Summarize a URL",
            )
        )

        assert events[0][0] == "status"
        assert events[0][1]["stage"] == "planning"
        assert events[0][1]["message"] == "Planning workflow"

    def test_stream_does_not_expose_planner_thought_deltas(self):
        model_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="Summarize a URL",
            )
        )

        planner_thoughts = [payload for name, payload in events if name == "thought" and payload["stage"] == "planner"]
        assert planner_thoughts == []

    def test_stream_emits_plan_then_result(self):
        model_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="Summarize a URL",
            )
        )

        event_names = [name for name, _ in events]
        assert event_names[0] == "status"
        assert "thought" in event_names
        assert "plan" in event_names
        assert event_names[-1] == "result"
        assert all(payload.get("stage") != "planner" for name, payload in events if name == "thought")
        assert events[0][1]["stage"] == "planning"
        building_status = next(
            payload for name, payload in events if name == "status" and payload["stage"] == "building"
        )
        assert building_status["message"] == "Building nodes"

        plan = next(payload for name, payload in events if name == "plan")
        assert plan["title"] == "URL Summarizer"
        assert plan["app_name"] == "Summarizer"
        assert plan["mode"] == "workflow"
        assert [n["node_type"] for n in plan["nodes"]] == ["start", "llm", "end"]
        assert plan["nodes"][0]["label"] == "Start"
        assert plan["nodes"][0]["purpose"] == "User submits URL."

        result = next(payload for name, payload in events if name == "result")
        assert result["error"] == ""
        assert result["mode"] == "workflow"
        assert [n["data"]["type"] for n in result["graph"]["nodes"]] == ["start", "llm", "end"]

    def test_stream_planner_failure_emits_only_result(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = RuntimeError("planner exploded")

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="x",
            )
        )

        assert [name for name, _ in events] == ["status", "planner_thinking", "result"]
        assert events[0][1]["stage"] == "planning"
        result = events[2][1]
        assert "planner exploded" in result["error"]
        assert result["graph"]["nodes"] == []
        assert result["mode"] == "workflow"
        assert result["context_checkpoint"]["version"] == 4

    def test_stream_and_blocking_results_match(self):
        """The streaming ``result`` event must equal the blocking return value."""
        stream_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())
        blocking_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        kwargs = {
            "model_parameters": {},
            "provider": "openai",
            "model_name": "gpt-4o",
            "model_mode": "chat",
            "mode": "advanced-chat",
            "instruction": "Greet me",
        }
        stream_events = list(WorkflowGenerator.generate_workflow_graph_stream(model_instance=stream_instance, **kwargs))
        stream_result = next(payload for name, payload in stream_events if name == "result")
        blocking_result = WorkflowGenerator.generate_workflow_graph(model_instance=blocking_instance, **kwargs)

        assert stream_result == blocking_result

    def test_blocking_result_includes_resolved_mode(self):
        """Task 3: the non-streaming envelope carries the resolved ``mode`` too."""
        model_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        assert result["mode"] == "workflow"

    def test_stream_emits_plan_ready_operation_after_plan(self):
        model_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="Summarize a URL",
            )
        )

        plan_index = next(index for index, (name, _) in enumerate(events) if name == "plan")
        plan_ready = next(
            (payload for name, payload in events if name == "operation" and payload.get("action") == "plan_ready"),
            None,
        )
        assert plan_ready is not None
        assert plan_ready["stage"] == "planning"
        assert plan_ready["count"] == 3
        assert plan_ready["message"] == "Planned 3 nodes"

        plan_ready_index = next(
            index
            for index, (name, payload) in enumerate(events)
            if name == "operation" and payload.get("action") == "plan_ready"
        )
        assert plan_ready_index > plan_index
        building_status_index = next(
            index
            for index, (name, payload) in enumerate(events)
            if name == "status" and payload.get("stage") == "building"
        )
        assert plan_ready_index < building_status_index

    def test_stream_emits_node_start_and_done_for_each_built_node(self):
        model_instance = _GraphFixtureModel(_stream_planner_json(), _stream_builder_json())

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="Summarize a URL",
            )
        )

        building_ops = [
            payload for name, payload in events if name == "operation" and payload.get("stage") == "building"
        ]
        starts = [op for op in building_ops if op["action"] == "node_start"]
        dones = [op for op in building_ops if op["action"] == "node_done"]
        assert len(starts) == 3
        assert len(dones) == 3

        labels_by_id = {op["node_id"]: op["label"] for op in starts}
        assert set(labels_by_id.values()) == {"Start", "Summarize", "End"}

        for node_id in labels_by_id:
            start_index = next(
                index
                for index, (name, payload) in enumerate(events)
                if name == "operation" and payload.get("action") == "node_start" and payload.get("node_id") == node_id
            )
            done_index = next(
                index
                for index, (name, payload) in enumerate(events)
                if name == "operation" and payload.get("action") == "node_done" and payload.get("node_id") == node_id
            )
            assert start_index < done_index
            label = labels_by_id[node_id]
            start = starts[next(i for i, op in enumerate(starts) if op["node_id"] == node_id)]
            done = dones[next(i for i, op in enumerate(dones) if op["node_id"] == node_id)]
            assert start["message"] == f"Generating node {label}"
            assert done["message"] == f"Node {label} completed"


class TestPlannerFailureDetailReachesEnvelope:
    """The generator envelope must carry the readable detail, not a type name."""

    def test_empty_planner_response_reports_the_empty_case(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result("")

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        details = [error["detail"] for error in result["errors"]]
        assert any("empty model response" in detail for detail in details)
        assert not any("Non-object JSON" in detail for detail in details)


def test_stage_error_to_envelope_code():
    err = InvokeError("invoke err")
    assert _stage_error_to_envelope_code(err) == "MODEL_ERROR"

    err2 = StageJSONError("builder", "json err")
    assert _stage_error_to_envelope_code(err2) == "INVALID_JSON"

    err3 = ValueError("other err")
    assert _stage_error_to_envelope_code(err3) == "MODEL_ERROR"
