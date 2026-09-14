"""Container and refine-mode integration tests for node building."""

from ._runner_test_support import (
    WorkflowGenerator,
    _GraphFixtureModel,
    json,
)


class TestWorkflowGeneratorContainerNodes:
    """
    Iteration / loop container support — postprocess must preserve the
    relative positions of inner nodes (those with parentId) and mark
    sibling edges with ``isInIteration`` / ``isInLoop`` so the canvas
    renders them inside the subgraph.
    """

    def _planner(self) -> str:
        return json.dumps(
            {
                "title": "Per-Item Summarize",
                "description": "Iterate a list of URLs and summarize each one.",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "Take a list of URLs."},
                    {"label": "Per URL", "node_type": "iteration", "purpose": "Loop over each URL."},
                    {"label": "Summarize", "node_type": "llm", "purpose": "Summarize one URL.", "parent": "Per URL"},
                    {"label": "End", "node_type": "end", "purpose": "Return summaries."},
                ],
            }
        )

    def _builder(self) -> str:
        # Mirrors a real iteration draft: container + auto-start child + inner
        # llm + an end node sibling. Inner nodes carry parentId; the inner
        # edge connects iteration-start → llm.
        return json.dumps(
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
                        "data": {
                            "type": "iteration",
                            "title": "Per URL",
                            "start_node_id": "node2start",
                            "iterator_selector": ["node1", "urls"],
                            "output_selector": ["node3", "text"],
                        },
                        "width": 808,
                        "height": 204,
                        "zIndex": 1,
                    },
                    {
                        "id": "node2start",
                        "type": "custom-iteration-start",
                        "parentId": "node2",
                        "extent": "parent",
                        "position": {"x": 60, "y": 78},
                        "data": {"type": "iteration-start", "title": "", "isInIteration": True},
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "parentId": "node2",
                        "extent": "parent",
                        "position": {"x": 240, "y": 60},
                        "data": {
                            "type": "llm",
                            "title": "Summarize",
                            "isInIteration": True,
                            "iteration_id": "node2",
                        },
                    },
                    {
                        "id": "node4",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "end",
                            "title": "End",
                            "outputs": [{"variable": "summaries", "value_selector": ["node2", "output"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2start", "target": "node3", "type": "custom"},
                    {"id": "e3", "source": "node2", "target": "node4", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_inner_node_positions_are_preserved(self):
        # Container children carry positions relative to their parent — the
        # auto-layout step must NOT override them, only top-level nodes get
        # the left-to-right re-flow.
        model_instance = _GraphFixtureModel(self._planner(), self._builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a list of URLs",
        )

        nodes_by_id = {n["id"]: n for n in result["graph"]["nodes"]}
        inner = nodes_by_id["node3"]
        # Position untouched (60, 60 — what the builder emitted, after the
        # iteration-start was (60, 78)).
        assert inner["position"]["x"] == 240
        assert inner["position"]["y"] == 60
        assert inner["zIndex"] == 1002
        assert inner["extent"] == "parent"

    def test_top_level_nodes_still_get_auto_layout(self):
        model_instance = _GraphFixtureModel(self._planner(), self._builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a list of URLs",
        )

        # 3 top-level nodes: start, iteration container, end — laid out
        # left-to-right.
        top_level = [n for n in result["graph"]["nodes"] if not n.get("parentId")]
        xs = [n["position"]["x"] for n in top_level]
        assert xs == sorted(xs)
        assert len(set(xs)) == 3

    def test_sibling_edges_inside_container_are_flagged(self):
        # The iteration-start → llm edge (both children of node2) must be
        # flagged isInIteration with iteration_id pointing at the container.
        # The edges crossing the container boundary must NOT be flagged.
        model_instance = _GraphFixtureModel(self._planner(), self._builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a list of URLs",
        )

        edges_by_id = {e["id"]: e for e in result["graph"]["edges"]}
        inner_edge = edges_by_id["node2start-source-node3-target"]
        assert inner_edge["data"]["isInIteration"] is True
        assert inner_edge["data"]["iteration_id"] == "node2"
        assert inner_edge["zIndex"] == 1002

        outside_edge = edges_by_id["node1-source-node2-target"]
        assert outside_edge["data"]["isInIteration"] is False
        assert outside_edge["data"]["isInLoop"] is False


class TestWorkflowGeneratorRefine:
    """
    Refine mode (cmd+k `/refine`): when ``current_graph`` is passed, the
    existing draft must be injected into BOTH stage prompts so the LLM amends
    the user's graph rather than inventing a new one. ``current_graph=None``
    (the default) keeps the create-from-scratch behaviour untouched.
    """

    def _current_graph(self) -> dict:
        return {
            "nodes": [
                {
                    "id": "node1",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "variables": []},
                },
                {
                    "id": "node2",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "llm",
                        "title": "Summarize",
                        "prompt_template": [{"role": "user", "text": "Summarize {{#node1.url#}}"}],
                    },
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "outputs": [
                            {
                                "variable": "result",
                                "value_selector": ["node2", "text"],
                                "value_type": "string",
                            }
                        ],
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }

    def _planner(self) -> str:
        return json.dumps(
            {
                "title": "Summarizer",
                "description": "x",
                "nodes": [
                    {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x", "action": "keep"},
                    {
                        "id": "node2",
                        "label": "Summarize",
                        "node_type": "llm",
                        "purpose": "x",
                        "action": "update",
                    },
                    {"id": "node3", "label": "End", "node_type": "end", "purpose": "x", "action": "keep"},
                ],
                "edges": [
                    {"source": "node1", "target": "node2"},
                    {"source": "node2", "target": "node3"},
                ],
            }
        )

    def _builder(self) -> str:
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start", "variables": []},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "llm", "title": "Summarize"},
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End"},
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_existing_graph_is_scoped_to_planner_and_updated_node(self):
        model_instance = _GraphFixtureModel(self._planner(), self._builder())

        WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Also translate the summary",
            current_graph=self._current_graph(),
        )

        planner_user_prompt = str(model_instance.invoke_llm.call_args_list[0].kwargs["prompt_messages"][1].content)
        builder_call = next(
            call
            for call in model_instance.invoke_llm.call_args_list
            if "id=node2, type=llm" in str(call.kwargs["prompt_messages"][1].content)
        )
        builder_user_prompt = str(builder_call.kwargs["prompt_messages"][1].content)

        # Planner: refine framing + compact summary (node ids/types).
        assert "Existing graph to refine" in planner_user_prompt
        assert "REFINING" in planner_user_prompt
        assert "type='llm'" in planner_user_prompt
        assert "node1 -> node2" in planner_user_prompt

        # The updated node builder sees its own existing semantic config only.
        assert "Existing config to preserve" in builder_user_prompt
        assert "{{#node1.url#}}" in builder_user_prompt

    def test_create_mode_injects_no_existing_graph_section(self):
        # With no current_graph the prompts must be byte-for-byte the create
        # flow — no stray "refine" framing leaks into a from-scratch generation.
        model_instance = _GraphFixtureModel(self._planner(), self._builder())

        WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize and translate a URL",
        )

        planner_user_prompt = str(model_instance.invoke_llm.call_args_list[0].kwargs["prompt_messages"][1].content)
        builder_call = next(
            call
            for call in model_instance.invoke_llm.call_args_list
            if "workflow planner" not in str(call.kwargs["prompt_messages"][0].content).lower()
        )
        builder_user_prompt = str(builder_call.kwargs["prompt_messages"][1].content)
        assert "Existing graph to refine" not in planner_user_prompt
        assert "Existing graph to refine" not in builder_user_prompt

    def test_refine_still_returns_a_valid_graph(self):
        # End-to-end: refine runs the same postprocess/validate path and yields
        # a clean graph envelope.
        model_instance = _GraphFixtureModel(self._planner(), self._builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Also translate the summary",
            current_graph=self._current_graph(),
        )

        assert result["error"] == ""
        types = [n["data"]["type"] for n in result["graph"]["nodes"]]
        assert types == ["start", "llm", "end"]
