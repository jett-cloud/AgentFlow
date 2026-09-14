"""Focused edge-case coverage for the workflow-generator facade."""

from types import SimpleNamespace

from graphon.model_runtime.entities.model_entities import ModelPropertyKey

from ._runner_test_support import (
    MagicMock,
    WorkflowGenerator,
    _GraphFixtureModel,
    _llm_result,
    _ParallelBuilderModel,
    json,
    node_config,
)


class TestWorkflowGeneratorEdgeCases:
    """
    Smaller behaviours that aren't part of the happy path but matter for
    coverage and resilience.
    """

    def test_clamp_for_planner_lowers_high_temperature(self):
        # The planner needs deterministic output — a permissive temperature
        # would let it ramble. The runner pins it back down for the planner
        # call while leaving the builder call alone.
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({"temperature": 0.9, "max_tokens": 1024})
        assert out["temperature"] == 0.2
        # Other params must flow through unchanged so the model still gets
        # provider-tuned defaults.
        assert out["max_tokens"] == 1024

    def test_interactive_planner_emits_clarification_and_does_not_build(self):
        clarification = {
            "action": "request_user_input",
            "questions": [
                {
                    "id": "format",
                    "question": "Which format?",
                    "options": [
                        {
                            "value": "markdown",
                            "label": "Markdown",
                            "description": "Readable output.",
                            "recommended": True,
                        },
                        {
                            "value": "json",
                            "label": "JSON",
                            "description": "Machine-readable output.",
                            "recommended": False,
                        },
                    ],
                    "allow_other": True,
                }
            ],
        }
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result(json.dumps(clarification))

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="Create a report",
                planner_policy="interactive",
            )
        )

        assert [name for name, _ in events] == ["status", "planner_thinking", "clarification"]
        assert events[-1][1]["questions"][0]["id"] == "format"
        assert events[-1][1]["context_checkpoint"]["version"] == 4
        assert events[-1][1]["context_checkpoint"]["budget"]["clarification_rounds"] == 1
        assert model_instance.invoke_llm.call_count == 1

    def test_interactive_planner_emits_assistant_message_without_building(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.return_value = _llm_result(
            json.dumps(
                {
                    "action": "respond_to_user",
                    "message": "I will retrieve matching passages and summarize them.",
                }
            )
        )

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=model_instance,
                model_parameters={},
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="How will you build this?",
                planner_policy="interactive",
            )
        )

        assert [name for name, _ in events] == ["status", "planner_thinking", "assistant_message"]
        assert events[-1][1]["message"] == "I will retrieve matching passages and summarize them."
        assert events[-1][1]["context_checkpoint"]["version"] == 4
        assert model_instance.invoke_llm.call_count == 1

    def test_context_limit_returns_stable_error_without_invoking_model(self):
        class _OversizedModel:
            def get_model_schema(self):
                return SimpleNamespace(
                    parameter_rules=[],
                    model_properties={ModelPropertyKey.CONTEXT_SIZE: 4096},
                )

            def get_llm_num_tokens(self, _prompt_messages):
                return 100000

            def invoke_llm(self, **_kwargs):
                raise AssertionError("model must not be invoked for oversized context")

        events = list(
            WorkflowGenerator.generate_workflow_graph_stream(
                model_instance=_OversizedModel(),
                model_parameters={},
                provider="openai",
                model_name="small-context",
                model_mode="chat",
                mode="workflow",
                instruction="Create a report",
            )
        )

        assert [name for name, _ in events] == ["status", "result"]
        assert events[-1][1]["errors"][0]["code"] == "PLANNER_CONTEXT_LIMIT"

    def test_builder_receives_only_resources_selected_by_the_plan(self):
        plan = {
            "title": "Search",
            "description": "Search the web.",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "Start."},
                {"id": "node2", "label": "Search", "node_type": "tool", "purpose": "Search."},
                {"id": "node3", "label": "End", "node_type": "end", "purpose": "End."},
            ],
            "edges": [
                {"source": "node1", "target": "node2"},
                {"source": "node2", "target": "node3"},
            ],
            "resource_requests": [
                {"kind": "tool", "provider_name": "google", "tool_name": "search", "reason": "Search."}
            ],
        }
        model = _ParallelBuilderModel(
            plan,
            {
                "node1": {"variables": []},
                "node2": {
                    "provider_id": "google",
                    "provider_name": "google",
                    "provider_type": "builtin",
                    "tool_name": "search",
                    "tool_label": "Search",
                    "tool_configurations": {},
                    "tool_parameters": {},
                },
                "node3": node_config("end"),
            },
            barrier_parties=0,
        )
        entries = [
            {
                "provider_name": "google",
                "provider_type": "builtin",
                "plugin_id": "",
                "tool_name": "search",
                "tool_label": "Web Search",
                "description": "Search the web.",
            },
            {
                "provider_name": "github",
                "provider_type": "builtin",
                "plugin_id": "",
                "tool_name": "issues",
                "tool_label": "Issues",
                "description": "List issues.",
            },
        ]

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="Search the web",
            tool_catalogue_entries=entries,
            installed_tools={("google", "search"), ("github", "issues")},
            context_checkpoint={
                "version": 4,
                "phase": "ready",
                "requirements": {
                    "search.tool": {
                        "status": "resolved",
                        "answer": {
                            "kind": "resource_mode",
                            "resource_kind": "tool",
                            "source": "workspace",
                            "binding_time": "design_time",
                        },
                        "source_turn_id": "turn-1",
                        "revision": 1,
                    }
                },
                "resource_intents": {
                    "web-search": {
                        "intent_id": "web-search",
                        "requirement_key": "search.tool",
                        "resource_kind": "tool",
                        "binding_time": "design_time",
                        "query": "web search",
                        "status": "bound",
                        "empty_queries": [],
                    }
                },
                "resource_bindings": {
                    "web-search": {
                        "intent_id": "web-search",
                        "requirement_key": "search.tool",
                        "resource_kind": "tool",
                        "resource_id": "google:search",
                        "resource_name": "Web Search",
                        "revision": 1,
                    }
                },
            },
        )

        assert result["error"] == ""
        planner_prompt = str(model.planner_prompt_messages[-1].content)
        builder_prompt = str(model.builder_prompt_messages["node2"][-1].content)
        assert "google/search" not in planner_prompt
        assert "github/issues" not in planner_prompt
        assert "google/search" in builder_prompt
        assert "github/issues" not in builder_prompt

    def test_clamp_for_planner_preserves_low_temperature(self):
        # A user who already picked a tight temperature shouldn't have their
        # setting overridden — clamping only kicks in above 0.5.
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({"temperature": 0.3})
        assert out["temperature"] == 0.3

    def test_clamp_for_planner_injects_default_when_missing(self):
        # No temperature → planner picks 0.2 so the output stays consistent
        # across calls.
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({})
        assert out["temperature"] == 0.2

    def test_clamp_for_planner_falls_back_when_model_declares_no_ceiling(self):
        # No caller budget and no declared model ceiling → the fallback keeps
        # large plans (roughly 60 tokens per pretty-printed node) intact.
        from core.workflow.generator.model_io.llm_response import (
            PLANNER_FALLBACK_MAX_TOKENS as _PLANNER_FALLBACK_MAX_TOKENS,
        )
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({})
        assert out["max_tokens"] == _PLANNER_FALLBACK_MAX_TOKENS

    def test_clamp_for_planner_uses_the_model_ceiling(self):
        # A model that declares a bigger output ceiling should get to use it —
        # a 70-node plan costs ~5.7k tokens once the model pretty-prints it.
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({}, 16384)
        assert out["max_tokens"] == 16384

    def test_clamp_for_planner_honours_a_ceiling_below_the_fallback(self):
        # A 4096-output model is the truth, not something to override.
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({}, 4096)
        assert out["max_tokens"] == 4096

    def test_clamp_for_planner_preserves_caller_max_tokens(self):
        # A caller who explicitly asked for a budget keeps it — we only fill
        # the default in when it's absent, never override an intentional value.
        from core.workflow.generator.model_io.llm_response import clamp_for_planner as _clamp_for_planner

        out = _clamp_for_planner({"max_tokens": 8192})
        assert out["max_tokens"] == 8192

    def test_planner_no_nodes_surfaces_clear_error(self):
        # The planner returned a malformed plan (empty nodes list). The runner
        # must refuse and tell the caller — never proceed to the builder.
        planner = json.dumps({"title": "x", "description": "x", "nodes": []})
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

        assert "no nodes" in result["error"].lower() or "no 'nodes'" in result["error"]
        # Builder must NOT have been called.
        assert model_instance.invoke_llm.call_count == 1

    def test_tool_catalogue_reaches_planner_and_only_the_tool_builder(self):
        planner = json.dumps(
            {
                "title": "x",
                "description": "x",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "Search", "node_type": "tool", "purpose": "Search with google/search."},
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
                        "data": {
                            "type": "tool",
                            "title": "Search",
                            "provider_id": "google",
                            "provider_name": "google",
                            "tool_name": "search",
                        },
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End"},
                    },
                ],
                "edges": [
                    {"id": "x", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "y", "source": "node2", "target": "node3", "type": "custom"},
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )
        model_instance = _GraphFixtureModel(planner, builder)

        WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
            tool_catalogue_text="- google/search — Search.",
        )

        all_prompts = []
        for call in model_instance.invoke_llm.call_args_list:
            for msg in call.kwargs["prompt_messages"]:
                all_prompts.append(str(msg.content))

        joined = "\n".join(all_prompts)
        assert joined.count("- google/search — Search.") == 2

    def test_postprocess_lays_out_nodes_left_to_right_regardless_of_input(self):
        # The LLM often returns wildly overlapping positions. The postprocess
        # step must override them with a clean horizontal layout so the
        # preview pane is readable.
        planner = json.dumps(
            {
                "title": "x",
                "description": "x",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "Middle", "node_type": "llm", "purpose": "x"},
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
                        "position": {"x": 999, "y": 999},
                        "data": {"type": "start", "title": "Start"},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 999, "y": 999},
                        "data": {"type": "llm", "title": "Middle"},
                    },
                    {
                        "id": "node3",
                        "type": "custom",
                        "position": {"x": 999, "y": 999},
                        "data": {"type": "end", "title": "End"},
                    },
                ],
                "edges": [
                    {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "b", "source": "node2", "target": "node3", "type": "custom"},
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
            mode="workflow",
            instruction="x",
        )

        positions = [n["position"]["x"] for n in result["graph"]["nodes"]]
        assert positions == sorted(positions)
        # All on the same Y so the canvas reads as a horizontal chain.
        ys = {n["position"]["y"] for n in result["graph"]["nodes"]}
        assert len(ys) == 1

    def test_postprocess_dedupes_repeated_edges(self):
        # LLMs frequently emit the same edge twice (once per direction or per
        # pass). The postprocess step must collapse them so the canvas
        # doesn't render visual duplicates.
        planner = json.dumps(
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
                "edges": [
                    {"id": "a", "source": "node1", "target": "node2", "type": "custom"},
                    {"id": "b", "source": "node1", "target": "node2", "type": "custom"},
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
            mode="workflow",
            instruction="x",
        )

        assert len(result["graph"]["edges"]) == 1
