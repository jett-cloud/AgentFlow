"""End-to-end tests for graph-validation errors in generator results."""

from ._runner_test_support import (
    GraphValidator,
    MagicMock,
    VariableReferences,
    WorkflowGenerator,
    _GraphFixtureModel,
    _llm_result,
    json,
)


class TestWorkflowGeneratorStructuredErrors:
    """
    The runner emits a ``errors: list[WorkflowGenerateErrorDict]`` sibling of
    ``error: str`` so the frontend can map machine-readable codes to localised
    copy and tie failures to specific nodes. These tests pin the codes the
    validator emits for each unhappy path; the FE i18n map (and any consumer
    decoding the envelope) relies on them being stable.
    """

    @staticmethod
    def _planner(nodes_spec):
        return json.dumps({"title": "x", "description": "x", "nodes": nodes_spec})

    @staticmethod
    def _builder(nodes, edges):
        return json.dumps({"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.7}})

    def test_happy_path_returns_empty_errors_list(self):
        # Even though older callers only read ``error``, the new ``errors``
        # field must be an empty list on success — never missing — so the
        # frontend's ``res.errors?.[0]?.code`` lookup is type-safe.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
            edges=[{"id": "x", "source": "node1", "target": "node2", "type": "custom"}],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        assert result["error"] == ""
        assert result["errors"] == []

    def test_validator_rejects_terminal_that_is_unreachable_from_start(self):
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Process", "node_type": "code", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
                {"id": "node1", "type": "custom", "position": {"x": 0, "y": 0}, "data": {"type": "start"}},
                {"id": "node2", "type": "custom", "position": {"x": 0, "y": 0}, "data": {"type": "code"}},
                {"id": "node3", "type": "custom", "position": {"x": 0, "y": 0}, "data": {"type": "end"}},
            ],
            edges=[{"source": "node2", "target": "node3"}],
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=_GraphFixtureModel(planner, builder),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert "INVALID_SCHEMA" in [error["code"] for error in result["errors"]]
        assert any("not reachable from start" in error["detail"] for error in result["errors"])

    def test_validator_rejects_knowledge_node_without_dataset_ids(self):
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Search", "node_type": "knowledge-retrieval", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
                {"id": "node1", "type": "custom", "position": {"x": 0, "y": 0}, "data": {"type": "start"}},
                {
                    "id": "node2",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "knowledge-retrieval"},
                },
                {"id": "node3", "type": "custom", "position": {"x": 0, "y": 0}, "data": {"type": "end"}},
            ],
            edges=[{"source": "node1", "target": "node2"}, {"source": "node2", "target": "node3"}],
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=_GraphFixtureModel(planner, builder),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
            installed_dataset_ids={"dataset-1"},
        )

        assert "UNKNOWN_DATASET" in [error["code"] for error in result["errors"]]

    def test_validator_rejects_dangling_parent_id(self):
        # The builder emitted an llm node whose ``parentId`` points at a node
        # that doesn't exist. That would silently render a free-floating node
        # in the canvas at run time; we fail at generation time instead.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "LLM", "node_type": "llm", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
                    "data": {"type": "llm", "title": "LLM", "parentId": "ghostcontainer"},
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "end", "title": "End"},
                },
            ],
            edges=[
                {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "b", "source": "node2", "target": "node3", "type": "custom"},
            ],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        codes = [e["code"] for e in result["errors"]]
        assert "UNKNOWN_NODE_REFERENCE" in codes

    def test_validator_rejects_container_without_children(self):
        # An iteration node with no inner children would deadlock at run time
        # (nothing to iterate over the array against). We surface
        # INVALID_CONTAINER so the user retries instead of hitting a runtime
        # error after Apply.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Loop", "node_type": "iteration", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
                    "data": {"type": "iteration", "title": "Loop"},
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "end", "title": "End"},
                },
            ],
            edges=[
                {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "b", "source": "node2", "target": "node3", "type": "custom"},
            ],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        codes = [e["code"] for e in result["errors"]]
        assert "INVALID_CONTAINER" in codes

    def test_validator_rejects_unknown_tool(self):
        # The builder emitted a tool node naming a provider / tool the tenant
        # doesn't have installed. The validator consults the
        # ``installed_tools`` set the service-layer passes in; a hallucinated
        # name fails with UNKNOWN_TOOL.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Search", "node_type": "tool", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
                        "type": "tool",
                        "title": "Search",
                        "provider_id": "google",
                        "provider_type": "builtin",
                        "provider_name": "google",
                        "tool_name": "fake_search",
                        "tool_label": "Fake",
                        "tool_node_version": "2",
                    },
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "end", "title": "End"},
                },
            ],
            edges=[
                {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "b", "source": "node2", "target": "node3", "type": "custom"},
            ],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
            # Only "real_search" is installed; "fake_search" is the hallucination.
            installed_tools={("google", "real_search")},
        )
        codes = [e["code"] for e in result["errors"]]
        assert "UNKNOWN_TOOL" in codes

    def test_validator_skips_tool_check_when_catalogue_is_none(self):
        # ``installed_tools=None`` is the sentinel the service uses when the
        # catalogue build itself failed (e.g. plugin daemon down). We must
        # NOT reject every tool node in that case — the user shouldn't be
        # blocked from generating just because the catalogue endpoint had
        # a hiccup.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Search", "node_type": "tool", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
                        "type": "tool",
                        "title": "Search",
                        "provider_id": "google",
                        "provider_name": "google",
                        "tool_name": "any_tool",
                    },
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "end", "title": "End"},
                },
            ],
            edges=[
                {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "b", "source": "node2", "target": "node3", "type": "custom"},
            ],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
            installed_tools=None,
        )
        codes = [e["code"] for e in result["errors"]]
        assert "UNKNOWN_TOOL" not in codes

    def test_validator_emits_missing_terminal_code(self):
        # The historical assertion was substring-based — pin the structured
        # code too so the frontend i18n map has a stable key.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Process", "node_type": "llm", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
                    "data": {"type": "llm", "title": "Process"},
                },
            ],
            edges=[{"source": "node1", "target": "node2"}],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        codes = [e["code"] for e in result["errors"]]
        assert "MISSING_TERMINAL" in codes

    def test_repairs_unresolved_reference_when_source_has_one_output(self):
        # The LLM node references a key the CODE node never declares, but the
        # source exposes exactly one output. Postprocessing can therefore
        # repair the selector without guessing or changing the graph shape.
        planner = self._planner(
            [
                {"label": "Start", "node_type": "start", "purpose": "x"},
                {"label": "Code", "node_type": "code", "purpose": "x"},
                {"label": "LLM", "node_type": "llm", "purpose": "x"},
                {"label": "End", "node_type": "end", "purpose": "x"},
            ]
        )
        builder = self._builder(
            nodes=[
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
                    "data": {"type": "code", "title": "Code", "outputs": {"summary": {"type": "string"}}},
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "llm",
                        "title": "LLM",
                        "prompt_template": [
                            {"role": "user", "text": "Look at {{#node2.mystery#}}."},
                        ],
                    },
                },
                {
                    "id": "node4",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "outputs": [{"variable": "out", "value_selector": ["node2", "mystery"]}],
                    },
                },
            ],
            edges=[
                {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "b", "source": "node2", "target": "node3", "type": "custom"},
                {"id": "c", "source": "node3", "target": "node4", "type": "custom"},
            ],
        )
        model_instance = _GraphFixtureModel(planner, builder)
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        assert result["error"] == ""
        llm_node = next(node for node in result["graph"]["nodes"] if node["id"] == "node3")
        assert llm_node["data"]["prompt_template"][0]["text"] == "Look at {{#node2.summary#}}."
        end_node = next(node for node in result["graph"]["nodes"] if node["id"] == "node4")
        assert end_node["data"]["outputs"][0]["value_selector"] == ["node2", "summary"]

    def test_keeps_unresolved_reference_when_source_outputs_are_ambiguous(self):
        nodes = [
            {
                "id": "node2",
                "data": {
                    "type": "code",
                    "outputs": {
                        "summary": {"type": "string"},
                        "details": {"type": "string"},
                    },
                },
            },
            {
                "id": "node3",
                "data": {
                    "type": "llm",
                    "prompt_template": [{"role": "user", "text": "Look at {{#node2.mystery#}}."}],
                },
            },
        ]

        VariableReferences._reconcile_variable_references(nodes=nodes, mode="workflow")

        errors = GraphValidator._collect_unresolved_refs(nodes=nodes, mode="workflow")
        assert errors == [
            {
                "code": "UNRESOLVED_REFERENCE",
                "detail": "Reference {#node2.mystery#} not declared on node 'node2'",
                "node_id": "node2",
            }
        ]

    def test_planner_json_failure_retries_once_then_recovers(self):
        # First planner response is non-JSON (the LLM wrapped the response in
        # prose) — we retry exactly once with a corrective system message,
        # the model returns valid JSON, and the rest of the pipeline runs as
        # if nothing went wrong. The builder must NOT be called more than
        # once (its parse still succeeded on first try).
        planner_valid = json.dumps(
            {
                "title": "x",
                "description": "x",
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
        fixture_model = _GraphFixtureModel(planner_valid, builder)
        first_call = True

        def invoke_with_invalid_json(**kwargs):
            nonlocal first_call
            if first_call:
                first_call = False
                return _llm_result("[]")
            return fixture_model._invoke(**kwargs)

        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = invoke_with_invalid_json
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        assert result["error"] == ""
        assert result["errors"] == []
        # Two planner attempts plus two node builders.
        assert model_instance.invoke_llm.call_count == 4

    def test_planner_json_failure_retries_only_once_then_gives_up(self):
        # Both planner attempts return junk. After the retry exhausts we
        # surface INVALID_JSON in the envelope and do NOT call the builder.
        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = [
            _llm_result("[]"),  # non-dict on first try
            _llm_result("[]"),  # non-dict on retry — give up
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
        codes = [e["code"] for e in result["errors"]]
        assert "INVALID_JSON" in codes
        # Exactly TWO calls — no third retry, no builder call.
        assert model_instance.invoke_llm.call_count == 2

    def test_planner_invalid_json_emits_invalid_json_code(self):
        # Stable code on the JSON-parse failure path so the FE can localise.
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result("definitely not json")
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )
        # ``json_repair`` is generous about repairing strings, so we can't
        # guarantee it always raises — but if it succeeds we still expect a
        # downstream schema failure. Either INVALID_JSON or INVALID_SCHEMA is
        # acceptable; both are FE-mapped to "couldn't understand the model
        # response" copy.
        codes = [e["code"] for e in result["errors"]]
        assert any(c in {"INVALID_JSON", "INVALID_SCHEMA", "MODEL_ERROR"} for c in codes)
