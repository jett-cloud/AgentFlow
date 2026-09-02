from typing import cast

from core.workflow.generator.graph_postprocessor import postprocess_graph
from core.workflow.generator.types import GraphDict


def test_postprocess_keeps_container_child_relative_position():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "box", "data": {"type": "iteration"}},
                {
                    "id": "child",
                    "parentId": "box",
                    "position": {"x": 240, "y": 60},
                    "data": {"type": "code"},
                },
            ],
            "edges": [],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    result = postprocess_graph(graph=graph, mode="workflow")

    child = next(node for node in result["nodes"] if node["id"] == "child")
    assert child["position"] == {"x": 240, "y": 60}


def test_postprocess_lays_out_piled_container_children_and_sizes_parent():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "box", "data": {"type": "iteration"}},
                {
                    "id": "boxstart",
                    "type": "custom-iteration-start",
                    "parentId": "box",
                    "data": {"type": "iteration-start"},
                },
                {
                    "id": "inner",
                    "parentId": "box",
                    "data": {"type": "llm"},
                },
            ],
            "edges": [{"source": "boxstart", "target": "inner"}],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    result = postprocess_graph(graph=graph, mode="workflow")
    start = next(node for node in result["nodes"] if node["id"] == "boxstart")
    inner = next(node for node in result["nodes"] if node["id"] == "inner")
    box = next(node for node in result["nodes"] if node["id"] == "box")

    assert start["position"]["x"] == 24.0
    assert start["position"]["y"] == 68.0
    assert inner["position"]["x"] > start["position"]["x"]
    assert box["width"] >= inner["position"]["x"] + 244
    assert box["height"] >= start["position"]["y"] + 100


def test_postprocess_lays_out_nested_containers_innermost_first():
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "outer", "data": {"type": "iteration"}},
                {
                    "id": "outerstart",
                    "type": "custom-iteration-start",
                    "parentId": "outer",
                    "data": {"type": "iteration-start"},
                },
                {"id": "inner", "parentId": "outer", "data": {"type": "loop"}},
                {
                    "id": "innerstart",
                    "type": "custom-loop-start",
                    "parentId": "inner",
                    "data": {"type": "loop-start"},
                },
                {"id": "leaf", "parentId": "inner", "data": {"type": "code"}},
            ],
            "edges": [
                {"source": "outerstart", "target": "inner"},
                {"source": "innerstart", "target": "leaf"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        },
    )

    result = postprocess_graph(graph=graph, mode="workflow")
    inner_start = next(node for node in result["nodes"] if node["id"] == "innerstart")
    leaf = next(node for node in result["nodes"] if node["id"] == "leaf")
    inner = next(node for node in result["nodes"] if node["id"] == "inner")
    outer_start = next(node for node in result["nodes"] if node["id"] == "outerstart")
    outer_child = next(node for node in result["nodes"] if node["id"] == "inner")

    assert inner_start["position"]["x"] < leaf["position"]["x"]
    assert inner["width"] > inner_start["position"]["x"]
    assert outer_start["position"]["x"] < outer_child["position"]["x"]


def test_postprocess_inserts_loop_start_and_wires_it_to_the_first_child() -> None:
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "loop1", "data": {"type": "loop", "title": "循环"}},
                {
                    "id": "inner",
                    "parentId": "loop1",
                    "data": {"type": "template-transform", "title": "模板转换"},
                },
            ],
            "edges": [],
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7},
        },
    )

    result = postprocess_graph(graph=graph, mode="workflow")
    loop = next(node for node in result["nodes"] if node["id"] == "loop1")
    start = next(node for node in result["nodes"] if (node.get("data") or {}).get("type") == "loop-start")

    assert start["parentId"] == "loop1"
    assert loop["data"]["start_node_id"] == start["id"]
    assert any(edge.get("source") == start["id"] and edge.get("target") == "inner" for edge in result["edges"])


def test_postprocess_wires_iteration_start_to_the_entry_child_not_downstream() -> None:
    graph = cast(
        GraphDict,
        {
            "nodes": [
                {"id": "iter1", "data": {"type": "iteration", "title": "迭代"}},
                {"id": "first", "parentId": "iter1", "data": {"type": "llm"}},
                {"id": "second", "parentId": "iter1", "data": {"type": "end"}},
            ],
            "edges": [{"source": "first", "target": "second"}],
            "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7},
        },
    )

    result = postprocess_graph(graph=graph, mode="workflow")
    start = next(node for node in result["nodes"] if (node.get("data") or {}).get("type") == "iteration-start")
    from_start = [edge.get("target") for edge in result["edges"] if edge.get("source") == start["id"]]

    assert from_start == ["first"]
    assert any(edge.get("source") == "first" and edge.get("target") == "second" for edge in result["edges"])


from ._runner_test_support import (
    GraphPostprocessor,
    WorkflowGenerator,
    _GraphFixtureModel,
    json,
)


class TestWorkflowGeneratorFileVariables:
    """The reported bug: a file-input workflow ("takes in a file, extract its
    content, summarize") generated a start node whose file variable lacked the
    required ``allowed_file_types``, so Studio rejected the draft with
    "supported file types is required". The builder now documents the field and
    the postprocessor backfills it as a final safety net."""

    @staticmethod
    def _planner() -> str:
        return json.dumps(
            {
                "title": "File Summarizer",
                "description": "Summarize an uploaded document into bullet points",
                "app_name": "File Summarizer",
                "icon": "📄",
                "start_inputs": [{"variable": "doc", "label": "Document", "type": "file"}],
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "Take a file"},
                    {"label": "Extract", "node_type": "document-extractor", "purpose": "Extract text"},
                    {"label": "Summarize", "node_type": "llm", "purpose": "Bullet points"},
                    {"label": "End", "node_type": "end", "purpose": "Return"},
                ],
            }
        )

    @staticmethod
    def _builder_file_var_missing_allowed_types() -> str:
        # The builder declares a file variable but (the bug) omits
        # allowed_file_types / upload methods.
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "start",
                            "title": "Start",
                            "variables": [{"variable": "doc", "label": "Document", "type": "file"}],
                        },
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "document-extractor",
                            "title": "Extract",
                            "variable_selector": ["node1", "doc"],
                            "is_array_file": False,
                        },
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "llm",
                            "title": "Summarize",
                            "prompt_template": [{"role": "user", "text": "Summarize {{#node2.text#}}"}],
                        },
                    },
                    {
                        "id": "node4",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "end",
                            "title": "End",
                            "outputs": [{"variable": "summary", "value_selector": ["node3", "text"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
                    {"id": "e3", "source": "node3", "target": "node4", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_backfills_allowed_file_types_so_draft_loads(self):
        model_instance = _GraphFixtureModel(self._planner(), self._builder_file_var_missing_allowed_types())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="takes in a file, extracting its content, then summarizing into bullet points",
        )

        assert result["error"] == ""
        start = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "start")
        doc = next(v for v in start["data"]["variables"] if v["variable"] == "doc")
        assert doc["type"] == "file"
        # The required field is now present and non-empty — the whole point.
        assert doc["allowed_file_types"]
        assert doc["allowed_file_upload_methods"] == ["local_file", "remote_url"]

    def test_builder_prompt_is_scoped_to_planned_node_types(self):
        model_instance = _GraphFixtureModel(self._planner(), self._builder_file_var_missing_allowed_types())

        WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize an uploaded file",
        )

        builder_call = next(
            call
            for call in model_instance.invoke_llm.call_args_list
            if "id=node2, type=document-extractor" in str(call.kwargs["prompt_messages"][1].content)
        )
        builder_prompt = str(builder_call.kwargs["prompt_messages"][0].content)
        assert "- document-extractor:" in builder_prompt
        # A node builder receives no schema for any other node type.
        assert "- start:" not in builder_prompt
        assert "- if-else:" not in builder_prompt
        assert "- tool" not in builder_prompt

    def test_promotes_mistyped_var_consumed_by_document_extractor(self):
        # A direct unit test of the backstop: a document-extractor reading a
        # paragraph-typed start var forces it to a file type.
        nodes = [
            {
                "id": "s",
                "data": {
                    "type": "start",
                    "variables": [{"variable": "doc", "label": "Doc", "type": "paragraph"}],
                },
            },
            {
                "id": "x",
                "data": {
                    "type": "document-extractor",
                    "variable_selector": ["s", "doc"],
                    "is_array_file": False,
                },
            },
        ]
        GraphPostprocessor._normalize_start_file_variables(nodes=nodes)
        doc = nodes[0]["data"]["variables"][0]
        assert doc["type"] == "file"
        assert doc["allowed_file_types"] == ["document"]

    def test_drops_custom_file_type_without_extensions(self):
        nodes = [
            {
                "id": "s",
                "data": {
                    "type": "start",
                    "variables": [
                        {
                            "variable": "f",
                            "label": "F",
                            "type": "file",
                            "allowed_file_types": ["custom"],
                            "allowed_file_extensions": [],
                        }
                    ],
                },
            }
        ]
        GraphPostprocessor._normalize_start_file_variables(nodes=nodes)
        f = nodes[0]["data"]["variables"][0]
        assert "custom" not in f["allowed_file_types"]
        assert f["allowed_file_types"]  # non-empty fallback

    def test_leaves_valid_file_variable_untouched(self):
        nodes = [
            {
                "id": "s",
                "data": {
                    "type": "start",
                    "variables": [
                        {
                            "variable": "img",
                            "label": "Img",
                            "type": "file",
                            "allowed_file_types": ["image"],
                            "allowed_file_upload_methods": ["local_file"],
                            "allowed_file_extensions": [],
                        }
                    ],
                },
            }
        ]
        GraphPostprocessor._normalize_start_file_variables(nodes=nodes)
        img = nodes[0]["data"]["variables"][0]
        assert img["allowed_file_types"] == ["image"]
        assert img["allowed_file_upload_methods"] == ["local_file"]

    def test_ignores_non_file_variables(self):
        nodes = [
            {
                "id": "s",
                "data": {
                    "type": "start",
                    "variables": [{"variable": "t", "label": "T", "type": "text-input"}],
                },
            }
        ]
        GraphPostprocessor._normalize_start_file_variables(nodes=nodes)
        assert "allowed_file_types" not in nodes[0]["data"]["variables"][0]


class TestWorkflowGeneratorLayeredLayout:
    """
    Top-level layout is computed from topology (longest-path layering), not
    array order: branches that run in parallel share a column and stack in
    lanes, and a join lands to the right of its deepest input.
    """

    @staticmethod
    def _node(node_id: str, node_type: str) -> dict:
        return {"id": node_id, "type": "custom", "data": {"type": node_type, "title": node_id}}

    def test_diamond_branches_share_a_column_in_separate_lanes(self):
        nodes = [
            self._node("start", "start"),
            self._node("branch", "if-else"),
            self._node("a", "llm"),
            self._node("b", "llm"),
            self._node("join", "variable-aggregator"),
        ]
        edges = [
            {"source": "start", "target": "branch"},
            {"source": "branch", "target": "a"},
            {"source": "branch", "target": "b"},
            {"source": "a", "target": "join"},
            {"source": "b", "target": "join"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        pos = {n["id"]: n["position"] for n in nodes}
        assert pos["start"]["x"] < pos["branch"]["x"] < pos["a"]["x"] < pos["join"]["x"]
        # The two arms share the column but not the lane.
        assert pos["a"]["x"] == pos["b"]["x"]
        assert pos["a"]["y"] != pos["b"]["y"]

    def test_out_of_order_node_array_still_flows_left_to_right(self):
        # Builder emitted the array end-first; topology must win.
        nodes = [
            self._node("end", "end"),
            self._node("middle", "llm"),
            self._node("start", "start"),
        ]
        edges = [
            {"source": "start", "target": "middle"},
            {"source": "middle", "target": "end"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        pos = {n["id"]: n["position"] for n in nodes}
        assert pos["start"]["x"] < pos["middle"]["x"] < pos["end"]["x"]

    def test_join_lands_right_of_its_deepest_branch(self):
        # start → a → b → join, start → join: BFS depth would put join at 1;
        # longest-path layering must put it at 3.
        nodes = [
            self._node("start", "start"),
            self._node("a", "llm"),
            self._node("b", "llm"),
            self._node("join", "end"),
        ]
        edges = [
            {"source": "start", "target": "a"},
            {"source": "a", "target": "b"},
            {"source": "b", "target": "join"},
            {"source": "start", "target": "join"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        pos = {n["id"]: n["position"] for n in nodes}
        assert pos["join"]["x"] > pos["b"]["x"] > pos["a"]["x"] > pos["start"]["x"]

    def test_container_children_are_not_repositioned(self):
        nodes = [
            self._node("start", "start"),
            self._node("iter", "iteration"),
            {
                "id": "inner",
                "type": "custom",
                "parentId": "iter",
                "position": {"x": 60.0, "y": 78.0},
                "data": {"type": "llm", "title": "inner"},
            },
            self._node("end", "end"),
        ]
        edges = [
            {"source": "start", "target": "iter"},
            {"source": "iter", "target": "end"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        inner = next(n for n in nodes if n["id"] == "inner")
        assert inner["position"] == {"x": 60.0, "y": 78.0}

    def test_container_does_not_overlap_its_top_level_successor(self):
        nodes = [
            self._node("start", "start"),
            {"id": "iteration", "width": 808, "height": 204, "data": {"type": "iteration", "title": "iteration"}},
            self._node("end", "end"),
        ]
        edges = [
            {"source": "start", "target": "iteration"},
            {"source": "iteration", "target": "end"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        positions = {node["id"]: node["position"] for node in nodes}
        assert positions["end"]["x"] > positions["iteration"]["x"] + 808

    def test_same_layer_nodes_stack_using_their_actual_heights(self):
        nodes = [
            self._node("start", "start"),
            {"id": "iteration", "width": 808, "height": 204, "data": {"type": "iteration", "title": "iteration"}},
            self._node("llm", "llm"),
        ]
        edges = [
            {"source": "start", "target": "iteration"},
            {"source": "start", "target": "llm"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        positions = {node["id"]: node["position"] for node in nodes}
        assert positions["llm"]["y"] >= positions["iteration"]["y"] + 204

    def test_cycle_members_are_parked_instead_of_hanging(self):
        # A cycle must not hang the layout pass; its members get parked one
        # layer past the laid-out nodes (validation flags the cycle itself).
        nodes = [
            self._node("start", "start"),
            self._node("a", "llm"),
            self._node("b", "llm"),
        ]
        edges = [
            {"source": "start", "target": "a"},
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ]

        GraphPostprocessor._layout_top_level_nodes(nodes=nodes, edges=edges)

        for node in nodes:
            assert "position" in node


class TestWorkflowGeneratorBranchHandleRepair:
    """
    Edges leaving if-else / question-classifier on the default "source"
    handle dangle off a handle that doesn't exist on the canvas. The repair
    pass re-homes them onto unused branch handles when (and only when) the
    assignment is unambiguous.
    """

    @staticmethod
    def _if_else_node() -> dict:
        return {
            "id": "branch",
            "data": {
                "type": "if-else",
                "cases": [{"case_id": "true", "conditions": []}],
            },
        }

    def test_assigns_true_then_false_to_default_handle_edges(self):
        nodes = [self._if_else_node()]
        edges = [
            {"source": "branch", "target": "a", "sourceHandle": "source"},
            {"source": "branch", "target": "b"},
        ]

        GraphPostprocessor._repair_branch_edge_handles(nodes=nodes, edges=edges)

        assert edges[0]["sourceHandle"] == "true"
        assert edges[1]["sourceHandle"] == "false"

    def test_respects_an_already_correct_handle(self):
        nodes = [self._if_else_node()]
        edges = [
            {"source": "branch", "target": "a", "sourceHandle": "true"},
            {"source": "branch", "target": "b", "sourceHandle": "source"},
        ]

        GraphPostprocessor._repair_branch_edge_handles(nodes=nodes, edges=edges)

        assert edges[0]["sourceHandle"] == "true"
        assert edges[1]["sourceHandle"] == "false"

    def test_leaves_ambiguous_assignments_alone(self):
        # Three default edges, only two free handles — guessing could swap
        # the IF and ELSE arms, so the repair must not touch anything.
        nodes = [self._if_else_node()]
        edges = [
            {"source": "branch", "target": "a", "sourceHandle": "source"},
            {"source": "branch", "target": "b", "sourceHandle": "source"},
            {"source": "branch", "target": "c", "sourceHandle": "source"},
        ]

        GraphPostprocessor._repair_branch_edge_handles(nodes=nodes, edges=edges)

        assert all(e["sourceHandle"] == "source" for e in edges)

    def test_question_classifier_uses_class_ids(self):
        nodes = [
            {
                "id": "qc",
                "data": {
                    "type": "question-classifier",
                    "classes": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}],
                },
            }
        ]
        edges = [
            {"source": "qc", "target": "a"},
            {"source": "qc", "target": "b"},
        ]

        GraphPostprocessor._repair_branch_edge_handles(nodes=nodes, edges=edges)

        assert edges[0]["sourceHandle"] == "1"
        assert edges[1]["sourceHandle"] == "2"

    def test_non_branch_nodes_are_untouched(self):
        nodes = [{"id": "llm1", "data": {"type": "llm"}}]
        edges = [{"source": "llm1", "target": "end", "sourceHandle": "source"}]

        GraphPostprocessor._repair_branch_edge_handles(nodes=nodes, edges=edges)

        assert edges[0]["sourceHandle"] == "source"


def test_repair_branch_edge_handles():
    nodes = [{"id": "n1", "data": {"type": "question-classifier", "classes": [{"id": "c1", "name": "c1"}]}}]
    edges = [{"source": "n1", "target": "n2", "sourceHandle": ""}]

    GraphPostprocessor._repair_branch_edge_handles(nodes=nodes, edges=edges)
    assert edges[0]["sourceHandle"] == "c1"


def test_document_extractor_start_vars():
    nodes = [{"id": "n1", "data": {"type": "document-extractor", "variable_selector": ["start", "doc"]}}]
    res = GraphPostprocessor._document_extractor_start_vars(nodes=nodes, start_id="start")
    assert res == {"doc": False}
