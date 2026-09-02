from core.workflow.generator.variable_references import collect_references, declared_outputs, declares_variable


def test_collect_references_finds_placeholder_and_selector():
    assert collect_references({"text": "{{#start.query#}}", "selector": ["llm", "text"]}) == {
        ("start", "query"),
        ("llm", "text"),
    }


def test_declares_llm_text_output():
    assert declares_variable({"data": {"type": "llm"}}, "text") is True


def test_declared_outputs_match_declares_variable_except_dynamic_tools():
    llm = {"data": {"type": "llm"}}
    assert declared_outputs(llm) == ["text"]
    assert declares_variable(llm, "text") is True
    assert declares_variable(llm, "other") is False

    legacy = {"data": {"type": "variable-assigner"}}
    assert declared_outputs(legacy) == ["output"]
    assert declares_variable(legacy, "output") is True
    assert declares_variable(legacy, "other") is False

    tool = {"data": {"type": "tool"}}
    assert declared_outputs(tool) == []
    # Tool outputs are dynamic: validation accepts any name even when none are listed.
    assert declares_variable(tool, "anything") is True

    tool_with_keys = {"data": {"type": "tool", "outputs": {"text": {}, "json": {}}}}
    assert declared_outputs(tool_with_keys) == ["text", "json"]
    assert declares_variable(tool_with_keys, "unlisted") is True


from ._runner_test_support import (
    GraphDict,
    Template,
    VariableReferences,
    WorkflowGenerator,
    _GraphFixtureModel,
    cast,
    deepcopy,
    json,
    postprocess_graph,
    pytest,
    validate_graph,
)


class TestSoleDeclaredVariable:
    """Human-input output inference feeds the variable-reference reconciler."""

    def test_single_human_input_output_is_inferred(self):
        node = {
            "data": {
                "type": "human-input",
                "inputs": [{"output_variable_name": "approval"}, "junk entry"],
            }
        }
        assert VariableReferences._sole_declared_variable(node) == "approval"

    def test_multiple_human_input_outputs_are_ambiguous(self):
        node = {
            "data": {
                "type": "human-input",
                "inputs": [{"output_variable_name": "a"}, {"output_variable_name": "b"}],
            }
        }
        assert VariableReferences._sole_declared_variable(node) is None

    def test_single_parameter_extractor_output_is_inferred(self):
        node = {"data": {"type": "parameter-extractor", "parameters": [{"name": "city"}]}}
        assert VariableReferences._sole_declared_variable(node) == "city"

    def test_list_operator_declares_its_fixed_outputs(self):
        node = {"data": {"type": "list-operator"}}
        assert VariableReferences._declares_variable(node, "first_record") is True
        assert VariableReferences._declares_variable(node, "not_an_output") is False

    def test_existing_llm_context_placeholder_is_left_untouched(self):
        llm_data = {"prompt_template": [{"role": "user", "text": "Answer using {{#context#}}"}]}
        VariableReferences._ensure_llm_context_placeholder(llm_data)
        assert llm_data["prompt_template"] == [{"role": "user", "text": "Answer using {{#context#}}"}]


class TestWorkflowGeneratorVariableReferences:
    """
    The builder used to emit ``{{#node1.url#}}`` inside an LLM prompt while
    the start node declared ``"variables": []`` — so the workflow saved
    fine but failed at run time with "variable not found" the moment the
    user clicked Run. Postprocess now walks every reference and auto-fixes
    the dominant failure mode (missing start-node variable).
    """

    def _planner_with_start_inputs(self) -> str:
        return json.dumps(
            {
                "title": "URL Summarizer",
                "description": "Summarize a URL.",
                "start_inputs": [
                    {"variable": "url", "label": "URL", "type": "text-input"},
                ],
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "Take URL."},
                    {"label": "Summarize", "node_type": "llm", "purpose": "Summarize."},
                    {"label": "End", "node_type": "end", "purpose": "Return."},
                ],
            }
        )

    def _planner_without_start_inputs(self) -> str:
        return json.dumps(
            {
                "title": "x",
                "description": "x",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "Summarize", "node_type": "llm", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )

    def _builder_referencing_missing_start_var(self, var: str = "url") -> str:
        # The LLM prompt references {{#node1.<var>#}} but the start node was
        # emitted with an empty variables array — the historical bug.
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
                        "data": {
                            "type": "llm",
                            "title": "Summarize",
                            "prompt_template": [
                                {"role": "system", "text": "You summarize URLs."},
                                {"role": "user", "text": f"Summarize this: {{{{#node1.{var}#}}}}"},
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
                            "outputs": [{"variable": "summary", "value_selector": ["node2", "text"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_auto_injects_missing_start_variable(self):
        # Even when the planner forgets to declare ``url`` in start_inputs and
        # the builder emits the dangling reference, postprocess must inject a
        # default ``url`` variable on the start node so the run-time resolver
        # can satisfy the LLM prompt.
        model_instance = _GraphFixtureModel(
            self._planner_without_start_inputs(), self._builder_referencing_missing_start_var("url")
        )

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        start = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "start")
        names = {v["variable"] for v in start["data"]["variables"]}
        assert "url" in names
        injected = next(v for v in start["data"]["variables"] if v["variable"] == "url")
        assert injected["label"] == "Url"
        assert injected["type"] == "paragraph"
        # And the generation still succeeds (no error envelope).
        assert result["error"] == ""

    def test_does_not_re_inject_declared_start_variable(self):
        # When the builder DID declare ``url`` on the start node, the walker
        # must leave it alone — we don't want duplicates or to overwrite the
        # builder-chosen type (text-input → paragraph would regress UX).
        builder = json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "start",
                            "title": "Start",
                            "variables": [
                                {
                                    "variable": "url",
                                    "label": "URL",
                                    "type": "text-input",
                                    "required": True,
                                    "max_length": 256,
                                    "options": [],
                                }
                            ],
                        },
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "llm",
                            "title": "Summarize",
                            "prompt_template": [
                                {"role": "user", "text": "Summarize {{#node1.url#}}"},
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
                            "outputs": [{"variable": "out", "value_selector": ["node2", "text"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(self._planner_with_start_inputs(), builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        start = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "start")
        urls = [v for v in start["data"]["variables"] if v["variable"] == "url"]
        # Exactly one ``url`` variable, with the builder-chosen ``text-input`` type.
        assert len(urls) == 1
        assert urls[0]["type"] == "text-input"

    def test_value_selector_references_are_walked(self):
        # value_selector references must also be considered — they're how end
        # nodes / code nodes / etc. read upstream outputs without prompt
        # interpolation. A dangling start-node variable in a selector should
        # be auto-injected, same as in a prompt placeholder.
        builder = json.dumps(
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
                        "data": {
                            "type": "code",
                            "title": "Process",
                            "code_language": "python3",
                            "code": "def main(topic): return {'result': topic}",
                            "variables": [
                                {"variable": "topic", "value_selector": ["node1", "topic"]},
                            ],
                            "outputs": {"result": {"type": "string", "children": None}},
                        },
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "end",
                            "title": "End",
                            "outputs": [{"variable": "out", "value_selector": ["node2", "result"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        planner_payload = json.loads(self._planner_without_start_inputs())
        planner_payload["nodes"][1].update({"label": "Process", "node_type": "code"})
        model_instance = _GraphFixtureModel(json.dumps(planner_payload), builder)

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        start = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "start")
        names = {v["variable"] for v in start["data"]["variables"]}
        assert "topic" in names

    def test_sys_query_is_resolved_in_advanced_chat_mode(self):
        # In Advanced-Chat mode the answer node typically references
        # ``{{#sys.query#}}`` — that's an automatic system variable, NOT
        # something the start node declares. The walker must not try to
        # auto-inject ``sys`` as a node-id or ``query`` as a start variable.
        planner = json.dumps(
            {
                "title": "Echo",
                "description": "Echo the user query.",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "Reply", "node_type": "answer", "purpose": "x"},
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
                        "data": {"type": "start", "title": "Start", "variables": []},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "answer",
                            "title": "Reply",
                            "variables": [],
                            "answer": "You said: {{#sys.query#}}",
                        },
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                ],
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
            instruction="Echo my question",
        )

        # No injection happened — the start node stays empty (sys.query is
        # automatic, no need for a declared variable).
        start = next(n for n in result["graph"]["nodes"] if n["data"]["type"] == "start")
        assert start["data"]["variables"] == []
        assert result["error"] == ""

    @pytest.mark.parametrize(
        ("mode", "terminal_type", "expected_selector", "expected_start_variables"),
        [
            ("advanced-chat", "answer", ["sys", "query"], []),
            ("workflow", "end", ["node1", "query"], ["query"]),
        ],
    )
    def test_normalizes_malformed_sys_query_selector(
        self,
        mode,
        terminal_type,
        expected_selector,
        expected_start_variables,
    ):
        terminal_data = {"type": terminal_type, "title": "Terminal"}
        if terminal_type == "answer":
            terminal_data["answer"] = "{{#node2.result#}}"
        else:
            terminal_data["outputs"] = [{"variable": "result", "value_selector": ["node2", "result"]}]
        graph = cast(
            GraphDict,
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
                        "data": {
                            "type": "code",
                            "title": "Code",
                            "variables": [{"variable": "query", "value_selector": ["sys,query"]}],
                            "outputs": {"result": {"type": "string"}},
                        },
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": terminal_data,
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "e2", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            },
        )

        result = postprocess_graph(graph=graph, mode=mode)

        start_node = next(node for node in result["nodes"] if node["id"] == "node1")
        code_node = next(node for node in result["nodes"] if node["id"] == "node2")
        assert code_node["data"]["variables"][0]["value_selector"] == expected_selector
        assert [variable["variable"] for variable in start_node["data"]["variables"]] == expected_start_variables
        assert validate_graph(graph=result, mode=mode) == []

    @pytest.mark.parametrize(
        "consumer_data",
        [
            {
                "type": "llm",
                "prompt_template": [{"role": "user", "text": "Question: {{#sys,query#}}"}],
            },
            {"type": "question-classifier", "query_variable_selector": ["sys.query"]},
            {"type": "knowledge-retrieval", "query_variable_selector": "sys.query"},
            {
                "type": "if-else",
                "cases": [{"conditions": [{"variable_selector": ["sys,query"]}]}],
            },
            {"type": "parameter-extractor", "query": [["sys", "query"]]},
            {"type": "variable-aggregator", "variables": [["sys.query"]]},
            {
                "type": "tool",
                "tool_parameters": {"query": {"type": "variable", "value": ["sys,query"]}},
            },
        ],
    )
    @pytest.mark.parametrize(("mode", "expected_node_id"), [("advanced-chat", "sys"), ("workflow", "node1")])
    def test_normalizes_sys_query_references_across_node_types(self, consumer_data, mode, expected_node_id):
        graph = cast(
            GraphDict,
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "start",
                            "title": "Start",
                            "variables": [],
                            # These are literals, not selectors, even though
                            # their values happen to resemble one.
                            "options": ["sys", "query"],
                        },
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"title": "Consumer", **deepcopy(consumer_data)},
                    },
                ],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            },
        )

        result = postprocess_graph(graph=graph, mode=mode)

        refs: set[tuple[str, str]] = set()
        consumer = next(node for node in result["nodes"] if node["id"] == "node2")
        VariableReferences._collect_refs_in_data(consumer["data"], refs)
        assert refs == {(expected_node_id, "query")}

        start = next(node for node in result["nodes"] if node["id"] == "node1")
        assert start["data"]["options"] == ["sys", "query"]
        expected_start_variables = [] if mode == "advanced-chat" else ["query"]
        assert [variable["variable"] for variable in start["data"]["variables"]] == expected_start_variables

    def test_repairs_llm_that_uses_only_one_of_two_incoming_retrieval_results(self):
        graph = cast(
            GraphDict,
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "start",
                            "title": "Start",
                            "variables": [{"variable": "query", "type": "paragraph"}],
                        },
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "knowledge-retrieval",
                            "title": "Knowledge A",
                            "dataset_ids": ["dataset-a"],
                            "query_variable_selector": ["node1", "query"],
                        },
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "knowledge-retrieval",
                            "title": "Knowledge B",
                            "dataset_ids": ["dataset-b"],
                            "query_variable_selector": ["node1", "query"],
                        },
                    },
                    {
                        "id": "node4",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "llm",
                            "title": "Synthesize",
                            "context": {"enabled": True, "variable_selector": ["node2", "result"]},
                            "prompt_template": [
                                {
                                    "role": "user",
                                    "text": "Answer using all retrieved knowledge.",
                                }
                            ],
                        },
                    },
                    {
                        "id": "node5",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {
                            "type": "end",
                            "title": "End",
                            "outputs": [{"variable": "answer", "value_selector": ["node4", "text"]}],
                        },
                    },
                ],
                "edges": [
                    {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "b", "source": "node1", "target": "node3", "type": "custom"},
                    {"id": "c", "source": "node2", "target": "node4", "type": "custom"},
                    {"id": "d", "source": "node3", "target": "node4", "type": "custom"},
                    {"id": "e", "source": "node4", "target": "node5", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            },
        )

        result = postprocess_graph(graph=graph, mode="workflow")

        llm = next(node for node in result["nodes"] if node["id"] == "node4")
        template = next(node for node in result["nodes"] if node["data"]["type"] == "template-transform")

        template_refs: set[tuple[str, str]] = set()
        VariableReferences._collect_refs_in_data(template["data"], template_refs)
        assert template_refs == {("node2", "result"), ("node3", "result")}
        rendered_context = Template(template["data"]["template"]).render(
            knowledge_1=[{"content": "Alpha result"}],
            knowledge_2=[{"content": "Beta result"}],
        )
        assert "## Knowledge source 1\nAlpha result" in rendered_context
        assert "## Knowledge source 2\nBeta result" in rendered_context
        assert llm["data"]["context"] == {
            "enabled": True,
            "variable_selector": [template["id"], "output"],
        }
        assert llm["data"]["prompt_template"][0]["text"] == ("Answer using all retrieved knowledge.\n\n{{#context#}}")
        assert {edge["source"] for edge in result["edges"] if edge["target"] == template["id"]} == {
            "node2",
            "node3",
        }
        assert {edge["source"] for edge in result["edges"] if edge["target"] == "node4"} == {template["id"]}
        assert validate_graph(graph=result, mode="workflow") == []

    def test_start_inputs_flow_into_builder_user_prompt(self):
        # The planner's ``start_inputs`` must be visible to the builder so
        # it can populate ``start.data.variables`` proactively. We sniff the
        # builder's user prompt to confirm the section is rendered.
        model_instance = _GraphFixtureModel(
            self._planner_with_start_inputs(), self._builder_referencing_missing_start_var("url")
        )

        WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Summarize a URL",
        )

        builder_call = next(
            call
            for call in model_instance.invoke_llm.call_args_list
            if "id=node1, type=start" in str(call.kwargs["prompt_messages"][1].content)
        )
        builder_user_prompt = str(builder_call.kwargs["prompt_messages"][1].content)
        # The Start inputs section must list ``url`` with its declared type.
        assert "Start inputs" in builder_user_prompt
        assert "variable='url'" in builder_user_prompt
        assert "type='text-input'" in builder_user_prompt

    def test_walker_matches_double_brace_placeholders_only(self):
        # Dify's run-time placeholder is ``{{#node.var#}}`` (DOUBLE braces) —
        # see graphon.runtime.variable_pool.VARIABLE_PATTERN. Single-brace
        # ``{#…#}`` is NOT a Dify placeholder, so even if the LLM emits one,
        # the walker should not treat it as a reference (the LLM-at-runtime
        # will see the literal single-brace string and ignore it; nothing
        # for us to validate).

        refs: set[tuple[str, str]] = set()
        VariableReferences._collect_refs_in_data(
            {
                "prompt_template": [
                    {"role": "user", "text": "Bad single: {#node1.url#}"},
                    {"role": "user", "text": "Good double: {{#node2.text#}}"},
                ],
            },
            refs,
        )

        # Single-brace entry is not picked up; only the double-brace one is.
        assert ("node2", "text") in refs
        assert ("node1", "url") not in refs


def test_declares_variable():
    # BuiltinNodeTypes is not imported directly, we need to mock or just use the generator method

    # LLM node
    assert VariableReferences._declares_variable({"data": {"type": "llm"}}, "text") == True
    llm_so = {"data": {"type": "llm", "structured_output": {"schema": {"properties": {"json_var": {}}}}}}
    assert VariableReferences._declares_variable(llm_so, "json_var") == True
    assert VariableReferences._declares_variable(llm_so, "other_var") == False

    # Code node
    assert (
        VariableReferences._declares_variable({"data": {"type": "code", "outputs": {"code_var": "str"}}}, "code_var")
        == True
    )

    # Knowledge retrieval
    assert VariableReferences._declares_variable({"data": {"type": "knowledge-retrieval"}}, "result") == True

    # Parameter extractor
    assert (
        VariableReferences._declares_variable(
            {"data": {"type": "parameter-extractor", "parameters": [{"name": "param1"}]}}, "param1"
        )
        == True
    )

    # HTTP request
    assert VariableReferences._declares_variable({"data": {"type": "http-request"}}, "body") == True

    # Template transform
    assert VariableReferences._declares_variable({"data": {"type": "template-transform"}}, "output") == True

    # Tool
    assert VariableReferences._declares_variable({"data": {"type": "tool"}}, "anything") == True

    # Other node (default false)
    assert VariableReferences._declares_variable({"data": {"type": "unknown"}}, "anything") == False


def test_postprocess_graph_edges():

    # Try calling _postprocess_graph directly to trigger _sanitize_node_ids
    graph = {
        "nodes": [{"id": "sys", "data": {"type": "start"}}, {"id": "bad id", "data": {"type": "llm"}}],
        "edges": [{"source": "sys", "target": "bad id", "id": "edge_1"}],
    }

    # Just mocking methods to reach the sanitize part or call directly
    VariableReferences._sanitize_node_ids(nodes=graph["nodes"], edges=graph["edges"])
    assert graph["nodes"][1]["id"] != "bad id"
