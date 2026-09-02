"""Node-id sanitization and reference-rewrite tests."""


from ._runner_test_support import (
    Any,
    VariableReferences,
    WorkflowGenerator,
    _GraphFixtureModel,
    json,
)


class TestWorkflowGeneratorNodeIdHyphens:
    """
    Dify's run-time placeholder regex
    (``graphon.runtime.variable_pool.VARIABLE_PATTERN``) accepts only
    ``[a-zA-Z0-9_]`` in the node-id slot. The builder LLM frequently
    emits ``node-1`` style hyphenated ids — left unfixed, every
    ``{{#node-1.var#}}`` placeholder silently fails to match at run time
    and the literal string survives into the LLM prompt, producing the
    "I got {{#node-1.text#}} back instead of real text" failure mode.

    Postprocess defensively strips hyphens out of every id + cross-
    reference before the rest of the pipeline touches them.
    """

    def _planner(self) -> str:
        return json.dumps(
            {
                "title": "Translator",
                "description": "Translate text.",
                "start_inputs": [{"variable": "text", "label": "Text", "type": "paragraph"}],
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "Translate", "node_type": "llm", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )

    def _hyphenated_builder(self) -> str:
        # Mimics what the builder LLM actually emits — hyphenated ids
        # everywhere, in node.id, edge.source/target, value_selector, and
        # ``{{#…#}}`` placeholders.
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "node-1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "start",
                            "title": "Start",
                            "variables": [
                                {
                                    "variable": "text",
                                    "label": "Text",
                                    "type": "paragraph",
                                    "required": True,
                                    "max_length": 4096,
                                    "options": [],
                                }
                            ],
                        },
                    },
                    {
                        "id": "node-2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "llm",
                            "title": "Translate",
                            "prompt_template": [
                                {"role": "user", "text": "Translate {{#node-1.text#}} to en, es, fr, de."},
                            ],
                        },
                    },
                    {
                        "id": "node-3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "end",
                            "title": "End",
                            "outputs": [{"variable": "result", "value_selector": ["node-2", "text"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node-1", "target": "node-2", "type": "custom"},
                    {"id": "e2", "source": "node-2", "target": "node-3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_strips_hyphens_from_every_node_id(self):
        # After postprocess, no node id and no cross-reference should
        # contain a hyphen — anything that did would fail at run time.
        model_instance = _GraphFixtureModel(self._planner(), self._hyphenated_builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Translate text",
        )

        # Node ids re-mapped.
        ids = [n["id"] for n in result["graph"]["nodes"]]
        assert ids == ["node1", "node2", "node3"]
        # Edge endpoints follow the rename.
        edge_endpoints = [(e["source"], e["target"]) for e in result["graph"]["edges"]]
        assert ("node1", "node2") in edge_endpoints
        assert ("node2", "node3") in edge_endpoints

    def test_rewrites_placeholder_string_when_id_is_remapped(self):
        # The whole reason for the remap — placeholders in prompt_template
        # must use the new id, otherwise the LLM at run time receives the
        # unsubstituted literal.
        model_instance = _GraphFixtureModel(self._planner(), self._hyphenated_builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Translate text",
        )

        llm_node = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "llm")
        user_text = next(p["text"] for p in llm_node["data"]["prompt_template"] if p["role"] == "user")
        # Old form is gone; new form is in.
        assert "{{#node-1.text#}}" not in user_text
        assert "{{#node1.text#}}" in user_text

    def test_rewrites_value_selector_lists(self):
        model_instance = _GraphFixtureModel(self._planner(), self._hyphenated_builder())

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Translate text",
        )

        end_node = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "end")
        selector = end_node["data"]["outputs"][0]["value_selector"]
        assert selector == ["node2", "text"]

    def test_leaves_already_clean_ids_untouched(self):
        # When the builder did the right thing the first time, the remap
        # should be a no-op — no spurious churn, no surprising rewrites.
        clean_builder = self._hyphenated_builder().replace("node-", "node")
        model_instance = _GraphFixtureModel(self._planner(), clean_builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        # No "node-" anywhere in the final graph.
        graph_blob = json.dumps(result["graph"])
        assert "node-" not in graph_blob

    def test_walker_does_not_match_hyphenated_placeholders(self):
        # The walker regex now mirrors Dify's run-time regex exactly, so a
        # hyphenated placeholder ``{{#node-1.url#}}`` no longer counts as a
        # detected reference. (The hyphen-strip pass runs first, so this
        # case shouldn't arise in practice, but the contract matters.)
        refs: set[tuple[str, str]] = set()
        VariableReferences._collect_refs_in_data(
            {"text": "Hyphenated: {{#node-1.url#}}. Clean: {{#node1.url#}}."}, refs
        )
        assert refs == {("node1", "url")}


class TestWorkflowGeneratorIdSanitization:
    """
    Beyond hyphens: the sanitize pass must handle ANY character the run-time
    placeholder regex rejects (dots, spaces, unicode) and must stay
    collision-safe when stripping makes two ids identical — silently merging
    ``node-1`` and ``node1`` would point every reference at one node.
    """

    def test_collision_between_stripped_and_existing_id_gets_a_suffix(self):
        nodes: list[dict[str, Any]] = [
            {"id": "node1", "data": {"type": "start", "variables": []}},
            {
                "id": "node-1",
                "data": {
                    "type": "llm",
                    "prompt_template": [{"role": "user", "text": "{{#node-1.text#}} and {{#node1.x#}}"}],
                },
            },
        ]
        edges = [{"id": "e", "source": "node1", "target": "node-1"}]

        VariableReferences._sanitize_node_ids(nodes=nodes, edges=edges)

        ids = [n["id"] for n in nodes]
        assert len(set(ids)) == 2
        assert ids[0] == "node1"
        renamed = ids[1]
        assert renamed != "node1"
        # Edge target follows the rename; references to the untouched sibling
        # stay untouched.
        assert edges[0]["target"] == renamed
        text = nodes[1]["data"]["prompt_template"][0]["text"]
        assert f"{{{{#{renamed}.text#}}}}" in text
        assert "{{#node1.x#}}" in text

    def test_sanitizes_dots_and_spaces(self):
        nodes: list[dict[str, Any]] = [
            {"id": "step.one", "data": {"type": "start", "variables": []}},
            {
                "id": "step two",
                "data": {"type": "llm", "prompt_template": [{"role": "user", "text": "{{#step two.text#}}"}]},
            },
        ]
        edges = [{"id": "e", "source": "step.one", "target": "step two"}]

        VariableReferences._sanitize_node_ids(nodes=nodes, edges=edges)

        assert [n["id"] for n in nodes] == ["stepone", "steptwo"]
        assert (edges[0]["source"], edges[0]["target"]) == ("stepone", "steptwo")
        assert "{{#steptwo.text#}}" in nodes[1]["data"]["prompt_template"][0]["text"]

    def test_id_with_no_valid_characters_gets_a_fallback(self):
        nodes = [
            {"id": "节点", "data": {"type": "start", "variables": []}},
            {"id": "node2", "data": {"type": "end", "outputs": []}},
        ]
        edges = [{"id": "e", "source": "节点", "target": "node2"}]

        VariableReferences._sanitize_node_ids(nodes=nodes, edges=edges)

        new_id = nodes[0]["id"]
        assert new_id
        assert new_id != "节点"
        assert edges[0]["source"] == new_id
