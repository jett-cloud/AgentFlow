import pytest

from core.workflow.generator.llm_response import StageSchemaError
from core.workflow.generator.node_builder import BuilderInput, _build_node, assemble_graph
from graphon.enums import BuiltinNodeTypes


def test_updated_child_without_parent_moves_out_of_container():
    graph = assemble_graph(
        plan_nodes=[
            {"id": "box", "label": "Loop", "node_type": "iteration", "purpose": "x", "action": "keep"},
            {"id": "step", "label": "Step", "node_type": "code", "purpose": "x", "action": "update"},
        ],
        plan_edges=[],
        configs_by_id={"step": {"outputs": {}}},
        existing_by_id={
            "box": {"id": "box", "data": {"type": "iteration", "title": "Loop"}},
            "step": {
                "id": "step",
                "parentId": "box",
                "data": {"type": "code", "isInIteration": True, "iteration_id": "box"},
            },
        },
    )

    step = next(node for node in graph["nodes"] if node["id"] == "step")
    assert "parentId" not in step
    assert "iteration_id" not in step["data"]


def test_container_children_without_explicit_edges_are_connected_in_declaration_order():
    graph = assemble_graph(
        plan_nodes=[
            {"id": "loop", "label": "Loop", "node_type": "loop", "purpose": "x"},
            {"id": "first", "label": "First", "node_type": "code", "purpose": "x", "parent": "loop"},
            {"id": "second", "label": "Second", "node_type": "code", "purpose": "x", "parent": "loop"},
            {"id": "third", "label": "Third", "node_type": "code", "purpose": "x", "parent": "loop"},
        ],
        plan_edges=[],
        configs_by_id={},
        existing_by_id={},
    )

    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == {
        ("loopstart", "first"),
        ("first", "second"),
        ("second", "third"),
    }


def test_container_explicit_internal_edges_are_not_replaced_by_auto_wiring():
    graph = assemble_graph(
        plan_nodes=[
            {"id": "iteration", "label": "Iteration", "node_type": "iteration", "purpose": "x"},
            {"id": "first", "label": "First", "node_type": "if-else", "purpose": "x", "parent": "iteration"},
            {"id": "second", "label": "Second", "node_type": "code", "purpose": "x", "parent": "iteration"},
            {"id": "third", "label": "Third", "node_type": "code", "purpose": "x", "parent": "iteration"},
        ],
        plan_edges=[{"source": "first", "target": "third", "source_handle": "true"}],
        configs_by_id={},
        existing_by_id={},
    )

    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("iterationstart", "first") in edges
    assert ("first", "third") in edges
    assert ("first", "second") not in edges
    assert ("second", "third") in edges


def test_builder_retries_a_chinese_node_when_user_visible_text_is_english():
    class RetryClient:
        def __init__(self):
            self.calls = 0

        def iter_json(self, *, messages, stage):
            self.calls += 1
            yield from ()
            if self.calls == 1:
                return {"config": {"prompt_template": [{"role": "user", "text": "Summarize the input."}]}}
            return {"config": {"prompt_template": [{"role": "user", "text": "请总结输入内容。"}]}}

    client = RetryClient()
    request = BuilderInput(
        provider="openai",
        model_name="gpt-4o",
        model_mode="chat",
        mode="workflow",
        instruction="生成中文摘要工作流",
        ideal_output="",
        plan_nodes=[],
        plan_edges=[],
        tool_catalogue_text="",
        knowledge_catalogue_text="",
        start_inputs=[],
        current_graph=None,
        output_language="zh-Hans",
    )

    config = _build_node(
        client=client,
        request=request,
        target_node={"id": "node2", "node_type": BuiltinNodeTypes.LLM, "label": "总结", "purpose": "总结内容"},
        plan_json="{}",
        mode_section="",
        existing_node=None,
        emit=None,
    )

    assert client.calls == 2
    assert config["prompt_template"][0]["text"] == "请总结输入内容。"


def test_builder_rejects_a_second_language_mismatch():
    class RetryClient:
        def __init__(self):
            self.calls = 0

        def iter_json(self, *, messages, stage):
            self.calls += 1
            yield from ()
            return {"config": {"answer": "Return the summary."}}

    client = RetryClient()
    request = BuilderInput(
        provider="openai",
        model_name="gpt-4o",
        model_mode="chat",
        mode="advanced-chat",
        instruction="生成中文摘要工作流",
        ideal_output="",
        plan_nodes=[],
        plan_edges=[],
        tool_catalogue_text="",
        knowledge_catalogue_text="",
        start_inputs=[],
        current_graph=None,
        output_language="zh-Hans",
    )

    with pytest.raises(StageSchemaError, match="requested Simplified Chinese"):
        _build_node(
            client=client,
            request=request,
            target_node={"id": "node3", "node_type": BuiltinNodeTypes.ANSWER, "label": "回复", "purpose": "输出摘要"},
            plan_json="{}",
            mode_section="",
            existing_node=None,
            emit=None,
        )

    assert client.calls == 2


from ._runner_test_support import (
    Any,
    MagicMock,
    WorkflowGenerator,
    _llm_result,
    _ParallelBuilderModel,
    cast,
    dify_config,
    json,
    time,
)


class TestParallelNodeBuilder:
    def test_builder_concurrency_caps_at_configured_workers(self, monkeypatch):
        monkeypatch.setattr(dify_config, "WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS", 2)
        planner = {
            "title": "URL Summarizer",
            "description": "Summarize a URL.",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Receive URL."},
                {"id": "node2", "label": "Summarize", "node_type": "llm", "purpose": "Summarize it."},
                {"id": "node3", "label": "End", "node_type": "end", "purpose": "Return summary."},
            ],
            "edges": [
                {"source": "node1", "target": "node2"},
                {"source": "node2", "target": "node3"},
            ],
        }
        model = _ParallelBuilderModel(
            planner,
            {
                "node1": {
                    "variables": [
                        {
                            "variable": "url",
                            "label": "URL",
                            "type": "text-input",
                            "required": True,
                            "max_length": 256,
                            "options": [],
                        }
                    ]
                },
                "node2": {
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                    "prompt_template": [{"role": "user", "text": "Summarize {{#node1.url#}}"}],
                    "context": {"enabled": False, "variable_selector": []},
                    "vision": {"enabled": False},
                },
                "node3": {"outputs": [{"variable": "summary", "value_selector": ["node2", "text"]}]},
            },
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        assert result["error"] == ""
        assert model.builder_calls == 3
        assert model.max_active_builders == 2
        assert [node["data"]["type"] for node in result["graph"]["nodes"]] == ["start", "llm", "end"]
        assert [edge["source"] for edge in result["graph"]["edges"]] == ["node1", "node2"]

    def test_higher_worker_config_runs_all_builders_in_one_wave(self, monkeypatch):
        monkeypatch.setattr(dify_config, "WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS", 5)
        planner = {
            "title": "URL Summarizer",
            "description": "Summarize a URL.",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Receive URL."},
                {"id": "node2", "label": "Summarize", "node_type": "llm", "purpose": "Summarize it."},
                {"id": "node3", "label": "End", "node_type": "end", "purpose": "Return summary."},
            ],
            "edges": [
                {"source": "node1", "target": "node2"},
                {"source": "node2", "target": "node3"},
            ],
        }
        # A 3-party barrier deadlocks unless all three builders run concurrently,
        # so passing at all proves the configured cap lifted the old 2-wave limit.
        model = _ParallelBuilderModel(
            planner,
            {
                "node1": {"variables": []},
                "node2": {
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                    "prompt_template": [{"role": "user", "text": "Summarize {{#sys.query#}}"}],
                    "context": {"enabled": False, "variable_selector": []},
                    "vision": {"enabled": False},
                },
                "node3": {"outputs": [{"variable": "summary", "value_selector": ["node2", "text"]}]},
            },
            barrier_parties=3,
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        assert result["error"] == ""
        assert model.builder_calls == 3
        assert model.max_active_builders == 3

    def test_failed_builder_cancels_queued_builders(self, monkeypatch):
        # One worker: node1's builder fails immediately, node2's blocks the
        # worker briefly, node3 sits in the queue. The failure must cancel
        # node3 before the worker frees up — no LLM call for it at all.
        monkeypatch.setattr(dify_config, "WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS", 1)
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "Mid", "node_type": "llm", "purpose": "x"},
                {"id": "node3", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}, {"source": "node2", "target": "node3"}],
        }
        builder_calls: list[str] = []

        class _FailFastModel:
            def invoke_llm(self, *, prompt_messages, model_parameters, stream):
                if "workflow planner" in str(prompt_messages[0].content).lower():
                    return _llm_result(json.dumps(planner))
                user_prompt = "\n".join(str(message.content) for message in prompt_messages)
                node_id = next(n for n in ("node1", "node2", "node3") if f"id={n}, type=" in user_prompt)
                builder_calls.append(node_id)
                if node_id == "node1":
                    raise RuntimeError("permanent provider failure")
                time.sleep(0.3)
                return _llm_result(json.dumps({"config": {}}))

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=_FailFastModel(),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["errors"][0]["code"] == "MODEL_ERROR"
        assert "node3" not in builder_calls

    def test_builder_response_without_config_object_fails_closed(self):
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        # node2's response parses as JSON but carries no ``config`` object — a
        # schema error, so no JSON-repair retry fires and the graph fails closed.
        model = _ParallelBuilderModel(planner, {"node1": {"variables": []}, "node2": cast(Any, "not an object")})

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert "missing 'config' object" in result["error"]
        assert result["errors"][0]["code"] == "INVALID_SCHEMA"
        assert result["graph"]["nodes"] == []
        assert model.calls_for("node2") == 1

    def test_refine_reuses_keep_nodes_and_only_builds_updated_nodes(self):
        planner = {
            "title": "Refined Summarizer",
            "description": "Use a shorter summary prompt.",
            "nodes": [
                {
                    "id": "start_existing",
                    "label": "Start",
                    "node_type": "start",
                    "purpose": "Receive topic.",
                    "action": "keep",
                },
                {
                    "id": "llm_existing",
                    "label": "Summarize",
                    "node_type": "llm",
                    "purpose": "Return one sentence.",
                    "action": "update",
                },
                {
                    "id": "end_existing",
                    "label": "End",
                    "node_type": "end",
                    "purpose": "Return summary.",
                    "action": "keep",
                },
            ],
            "edges": [
                {"source": "start_existing", "target": "llm_existing"},
                {"source": "llm_existing", "target": "end_existing"},
            ],
        }
        model = _ParallelBuilderModel(
            planner,
            {
                "llm_existing": {
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                    "prompt_template": [
                        {"role": "user", "text": "Summarize {{#start_existing.topic#}} in one sentence."}
                    ],
                    "context": {"enabled": False, "variable_selector": []},
                    "vision": {"enabled": False},
                }
            },
        )
        current_graph = {
            "nodes": [
                {
                    "id": "start_existing",
                    "type": "custom",
                    "position": {"x": 10, "y": 10},
                    "data": {
                        "type": "start",
                        "title": "Start",
                        "variables": [
                            {
                                "variable": "topic",
                                "label": "Topic",
                                "type": "paragraph",
                                "required": True,
                                "max_length": 4096,
                                "options": [],
                            }
                        ],
                    },
                },
                {
                    "id": "llm_existing",
                    "type": "custom",
                    "position": {"x": 330, "y": 10},
                    "data": {"type": "llm", "title": "Summarize", "prompt_template": []},
                },
                {
                    "id": "end_existing",
                    "type": "custom",
                    "position": {"x": 650, "y": 10},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "outputs": [{"variable": "summary", "value_selector": ["llm_existing", "text"]}],
                    },
                },
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Make the summary one sentence",
            current_graph=current_graph,
        )

        assert result["error"] == ""
        assert model.builder_calls == 1
        start = next(node for node in result["graph"]["nodes"] if node["id"] == "start_existing")
        assert start["data"]["variables"][0]["variable"] == "topic"
        assert current_graph["nodes"][0]["position"] == {"x": 10, "y": 10}

    def test_refine_does_not_send_or_replace_existing_http_secrets(self):
        planner = {
            "title": "Refined Request",
            "description": "Keep the request secure.",
            "nodes": [
                {"id": "start", "label": "Start", "node_type": "start", "purpose": "Start.", "action": "keep"},
                {
                    "id": "request",
                    "label": "Request",
                    "node_type": "http-request",
                    "purpose": "Call the API.",
                    "action": "update",
                },
                {"id": "end", "label": "End", "node_type": "end", "purpose": "End.", "action": "keep"},
            ],
            "edges": [{"source": "start", "target": "request"}, {"source": "request", "target": "end"}],
        }
        model = _ParallelBuilderModel(
            planner,
            {
                "request": {
                    "method": "post",
                    "timeout": {"max_read_timeout": 30},
                }
            },
        )
        current_graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "variables": []},
                },
                {
                    "id": "request",
                    "type": "custom",
                    "position": {"x": 320, "y": 0},
                    "data": {
                        "type": "http-request",
                        "title": "Request",
                        "method": "get",
                        "url": "https://example.com",
                        "headers": "Authorization: Bearer super-secret-header",
                        "authorization": {
                            "type": "api-key",
                            "config": {"type": "bearer", "api_key": "super-secret-api-key"},
                        },
                    },
                },
                {
                    "id": "end",
                    "type": "custom",
                    "position": {"x": 640, "y": 0},
                    "data": {"type": "end", "title": "End", "outputs": []},
                },
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Change the request to POST",
            current_graph=current_graph,
        )

        prompt = "\n".join(str(message.content) for message in model.builder_prompt_messages["request"])
        assert "super-secret-api-key" not in prompt
        assert "super-secret-header" not in prompt
        request = next(node for node in result["graph"]["nodes"] if node["id"] == "request")
        assert request["data"]["method"] == "post"
        assert request["data"]["authorization"] == current_graph["nodes"][1]["data"]["authorization"]
        assert request["data"]["headers"] == current_graph["nodes"][1]["data"]["headers"]

    def test_human_input_outputs_and_action_handles_follow_main_contract(self):
        planner = {
            "title": "Approval Flow",
            "description": "Ask a person to approve.",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Start."},
                {
                    "id": "node2",
                    "label": "Review",
                    "node_type": "human-input",
                    "purpose": "Collect approval and a comment.",
                },
                {"id": "node3", "label": "End", "node_type": "end", "purpose": "Return comment."},
            ],
            "edges": [
                {"source": "node1", "target": "node2"},
                {"source": "node2", "target": "node3", "source_handle": "approve"},
            ],
        }
        model = _ParallelBuilderModel(
            planner,
            {
                "node1": {"variables": []},
                "node2": {
                    "delivery_methods": [{"id": "webapp", "type": "webapp", "enabled": True}],
                    "form_content": "Approve this request.",
                    "inputs": [
                        {
                            "type": "paragraph",
                            "output_variable_name": "comment",
                            "default": {"type": "constant", "selector": [], "value": ""},
                        }
                    ],
                    "user_actions": [{"id": "approve", "title": "Approve", "button_style": "primary"}],
                    "timeout": 3,
                    "timeout_unit": "day",
                },
                "node3": {"outputs": [{"variable": "comment", "value_selector": ["node2", "comment"]}]},
            },
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Ask for approval",
        )

        assert result["error"] == ""
        review_edge = next(edge for edge in result["graph"]["edges"] if edge["source"] == "node2")
        assert review_edge["sourceHandle"] == "approve"

    def test_invalid_fragment_retries_once_then_fails_without_partial_graph(self):
        planner = {
            "title": "Minimal Flow",
            "description": "Return a fixed value.",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Start."},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "Return output."},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        model = _ParallelBuilderModel(
            planner,
            {
                "node1": {"variables": []},
                "node2": {"outputs": []},
            },
            invalid_node_id="node2",
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Return a fixed value",
        )

        assert result["graph"]["nodes"] == []
        assert {error["code"] for error in result["errors"]} == {"INVALID_JSON"}
        assert model.calls_for("node2") == 2

    def test_planner_schema_retries_once_then_uses_single_builder_contract(self):
        invalid_plan = {
            "title": "Minimal Flow",
            "description": "Return a fixed value.",
            "nodes": [
                {"label": "Start", "node_type": "start", "purpose": "Start."},
                {"label": "End", "node_type": "end", "purpose": "Return output."},
            ],
        }
        valid_plan = {
            **invalid_plan,
            "nodes": [
                {"id": "node1", **invalid_plan["nodes"][0]},
                {"id": "node2", **invalid_plan["nodes"][1]},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        planner_calls = 0

        def invoke(*, prompt_messages, model_parameters, stream):
            nonlocal planner_calls
            system_prompt = str(prompt_messages[0].content)
            if "workflow planner" in system_prompt.lower():
                planner_calls += 1
                return _llm_result(json.dumps(invalid_plan if planner_calls == 1 else valid_plan))
            prompt = "\n".join(str(message.content) for message in prompt_messages)
            config = {"variables": []} if "id=node1, type=start" in prompt else {"outputs": []}
            return _llm_result(json.dumps({"config": config}))

        model = MagicMock()
        model.invoke_llm.side_effect = invoke

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Return a fixed value",
        )

        assert result["error"] == ""
        assert planner_calls == 2
        retry_prompt = str(model.invoke_llm.call_args_list[1].kwargs["prompt_messages"][-1].content)
        assert "required topology schema" in retry_prompt


class TestAssembleParallelGraph:
    """Direct assembly contracts not exercised by the fixture-driven pipeline tests."""

    def test_loop_children_are_stamped_and_wired_to_loop_start(self):
        plan_nodes = [
            {"id": "node1", "label": "Retry Loop", "node_type": "loop", "purpose": "x"},
            {"id": "node2", "label": "Step", "node_type": "llm", "purpose": "x", "parent": "Retry Loop"},
        ]

        graph = assemble_graph(
            plan_nodes=plan_nodes,
            plan_edges=[],
            configs_by_id={"node1": {}, "node2": {}},
            existing_by_id={},
        )

        child = next(node for node in graph["nodes"] if node["id"] == "node2")
        assert child["parentId"] == "node1"
        assert child["data"]["isInLoop"] is True
        assert child["data"]["loop_id"] == "node1"
        loop_start = next(node for node in graph["nodes"] if node["id"] == "node1start")
        assert loop_start["data"]["type"] == "loop-start"
        assert any(edge["source"] == "node1start" and edge["target"] == "node2" for edge in graph["edges"])

    def test_planned_edge_handles_are_copied_to_graph_edges(self):
        plan_nodes = [
            {"id": "node1", "label": "Branch", "node_type": "if-else", "purpose": "x"},
            {"id": "node2", "label": "Then", "node_type": "llm", "purpose": "x"},
        ]

        graph = assemble_graph(
            plan_nodes=plan_nodes,
            plan_edges=[{"source": "node1", "target": "node2", "source_handle": "case1", "target_handle": "target"}],
            configs_by_id={"node1": {}, "node2": {}},
            existing_by_id={},
        )

        edge = graph["edges"][0]
        assert edge["sourceHandle"] == "case1"
        assert edge["targetHandle"] == "target"

    def test_kept_child_without_planned_parent_recovers_containment(self):
        # Refine plans rarely re-state ``parent`` on kept children; the
        # deepcopied wrapper's parentId must keep the child wired to the
        # container's synthetic start node.
        plan_nodes = [
            {"id": "node1", "label": "Per Item", "node_type": "iteration", "purpose": "x", "action": "keep"},
            {"id": "node2", "label": "Step", "node_type": "llm", "purpose": "x", "action": "keep"},
        ]
        existing_by_id = {
            "node1": {
                "id": "node1",
                "data": {"type": "iteration", "title": "Per Item", "start_node_id": "node1start"},
            },
            "node2": {
                "id": "node2",
                "parentId": "node1",
                "extent": "parent",
                "position": {"x": 240, "y": 60},
                "data": {"type": "llm", "title": "Step", "isInIteration": True, "iteration_id": "node1"},
            },
        }

        graph = assemble_graph(
            plan_nodes=plan_nodes,
            plan_edges=[],
            configs_by_id={},
            existing_by_id=existing_by_id,
            existing_edges=[{"source": "node1start", "target": "node2"}],
        )

        child = next(node for node in graph["nodes"] if node["id"] == "node2")
        assert child["parentId"] == "node1"
        assert any(edge["source"] == "node1start" and edge["target"] == "node2" for edge in graph["edges"])

    def test_updated_child_without_planned_parent_moves_out_of_existing_container(self):
        plan_nodes = [
            {"id": "node1", "label": "Per Item", "node_type": "iteration", "purpose": "x", "action": "keep"},
            {"id": "node2", "label": "Moved Step", "node_type": "code", "purpose": "x", "action": "update"},
        ]
        existing_by_id = {
            "node1": {
                "id": "node1",
                "data": {"type": "iteration", "title": "Per Item", "start_node_id": "node1start"},
            },
            "node2": {
                "id": "node2",
                "parentId": "node1",
                "extent": "parent",
                "position": {"x": 240, "y": 60},
                "data": {"type": "code", "title": "Step", "isInIteration": True, "iteration_id": "node1"},
            },
        }

        graph = assemble_graph(
            plan_nodes=plan_nodes,
            plan_edges=[],
            configs_by_id={"node2": {"outputs": {}}},
            existing_by_id=existing_by_id,
            existing_edges=[],
        )

        child = next(node for node in graph["nodes"] if node["id"] == "node2")
        assert "parentId" not in child
        assert "isInIteration" not in child["data"]
        assert "iteration_id" not in child["data"]

    def test_kept_node_with_removed_container_sheds_stale_markers(self):
        plan_nodes = [{"id": "node2", "label": "Step", "node_type": "llm", "purpose": "x", "action": "keep"}]
        existing_by_id = {
            "node2": {
                "id": "node2",
                "parentId": "gone",
                "extent": "parent",
                "zIndex": 1002,
                "position": {"x": 240, "y": 60},
                "data": {"type": "llm", "title": "Step", "isInIteration": True, "iteration_id": "gone"},
            }
        }

        graph = assemble_graph(
            plan_nodes=plan_nodes,
            plan_edges=[],
            configs_by_id={},
            existing_by_id=existing_by_id,
            existing_edges=[],
        )

        node = graph["nodes"][0]
        for wrapper_key in ("parentId", "extent", "zIndex", "position"):
            assert wrapper_key not in node
        for marker_key in ("isInIteration", "iteration_id"):
            assert marker_key not in node["data"]

    def test_refine_entry_edge_keeps_existing_target_over_plan_order(self):
        # The planner lists container children in arbitrary order; a kept
        # container's entry edge must follow the existing draft, not the list.
        plan_nodes = [
            {"id": "it", "label": "Per Item", "node_type": "iteration", "purpose": "x"},
            {"id": "b", "label": "B", "node_type": "llm", "purpose": "x", "parent": "Per Item"},
            {"id": "a", "label": "A", "node_type": "llm", "purpose": "x", "parent": "Per Item"},
        ]

        graph = assemble_graph(
            plan_nodes=plan_nodes,
            plan_edges=[{"source": "a", "target": "b"}],
            configs_by_id={"it": {}, "a": {}, "b": {}},
            existing_by_id={},
            existing_edges=[{"source": "itstart", "target": "a"}],
        )

        entry = next(edge for edge in graph["edges"] if edge["source"] == "itstart")
        assert entry["target"] == "a"
