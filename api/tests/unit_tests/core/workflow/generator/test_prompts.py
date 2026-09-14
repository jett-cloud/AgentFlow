"""Unit tests for compact planner and per-node builder prompt helpers."""

import json

from core.workflow.generator.prompts.node_builder_prompts import (
    format_knowledge_catalogue_section as format_node_knowledge_catalogue_section,
)
from core.workflow.generator.prompts.node_builder_prompts import (
    format_mode_section,
    format_parallel_plan,
    format_start_inputs_section,
    get_node_builder_system_prompt,
)
from core.workflow.generator.prompts.node_builder_prompts import (
    format_tool_catalogue_section as format_node_tool_catalogue_section,
)
from core.workflow.generator.prompts.planner_prompts import (
    PLANNER_SYSTEM_PROMPT,
    format_existing_graph_section,
    format_ideal_output_section,
    format_knowledge_catalogue_section,
)


def test_planner_protocol_requires_requirement_gate_before_resource_resolution():
    assert '"action":"acknowledge_turn"' in PLANNER_SYSTEM_PROMPT
    assert '"action":"resolve_resource"' in PLANNER_SYSTEM_PROMPT
    assert '"kind":"resource_mode"' in PLANNER_SYSTEM_PROMPT
    assert "Do not use search_tools or search_knowledge" in PLANNER_SYSTEM_PROMPT


from core.workflow.generator.prompts.planner_prompts import (
    format_tool_catalogue_section as format_planner_tool_catalogue_section,
)


class TestPlannerSystemPrompt:
    def test_requires_user_visible_plan_content_in_requested_language(self):
        assert "# Output language" in PLANNER_SYSTEM_PROMPT
        assert "title, description, app_name, node label, node purpose" in PLANNER_SYSTEM_PROMPT

    def test_documents_the_mode_output_field(self):
        """Auto-mode resolution rides on the planner echoing its mode choice."""
        assert '"mode": "workflow | advanced-chat"' in PLANNER_SYSTEM_PROMPT
        assert "When the ``# Mode`` section says auto, YOU decide" in PLANNER_SYSTEM_PROMPT

    def test_documents_agent_v2_node_type(self):
        assert '"agent"' in PLANNER_SYSTEM_PROMPT
        assert "Dify Agent Node v2" in PLANNER_SYSTEM_PROMPT
        assert 'Emits version "2" nodes' in PLANNER_SYSTEM_PROMPT

    def test_does_not_cap_the_node_count(self):
        """A 70-step request must not be squeezed into a 3–6-node plan."""
        assert "there is NO upper bound" in PLANNER_SYSTEM_PROMPT
        assert "drop or merge a step the user asked for" in PLANNER_SYSTEM_PROMPT

    def test_requires_compact_json_output(self):
        """Pretty-printing costs ~35% more tokens and truncates long plans."""
        assert "Emit it COMPACT" in PLANNER_SYSTEM_PROMPT
        assert "no indentation" in PLANNER_SYSTEM_PROMPT

    def test_documents_all_current_start_input_types(self):
        assert '"checkbox"' in PLANNER_SYSTEM_PROMPT
        assert '"json_object"' in PLANNER_SYSTEM_PROMPT
        assert 'never emit "json-object"' in PLANNER_SYSTEM_PROMPT


class TestFormatIdealOutputSection:
    def test_returns_empty_string_for_blank_input(self):
        assert format_ideal_output_section("") == ""
        assert format_ideal_output_section("   \n\t  ") == ""

    def test_wraps_content_in_a_labelled_section(self):
        out = format_ideal_output_section("A short summary.")

        assert out.startswith("# Ideal output")
        assert "A short summary." in out
        assert out.endswith("\n\n")


class TestToolCatalogueSections:
    def test_planner_returns_empty_when_catalogue_is_blank(self):
        assert format_planner_tool_catalogue_section("") == ""
        assert format_planner_tool_catalogue_section("   ") == ""

    def test_planner_includes_catalogue(self):
        out = format_planner_tool_catalogue_section("- google/search — Search.")

        assert "# Available tools" in out
        assert "planner" in out.lower()
        assert "- google/search — Search." in out

    def test_knowledge_catalogue_section_requires_exact_dataset_ids(self):
        out = format_knowledge_catalogue_section("- id=dataset-1 name=Product Docs — Documentation.")

        assert "# Available knowledge bases" in out
        assert "dataset_ids" in out
        assert "id=dataset-1" in out

    def test_node_builder_returns_empty_when_catalogue_is_blank(self):
        assert format_node_tool_catalogue_section("") == ""

    def test_node_builder_requires_exact_provider_and_tool_ids(self):
        out = format_node_tool_catalogue_section("- google/search — Search.")

        assert "exact" in out.lower()
        assert "provider_id" in out
        assert "tool_name" in out
        assert "- google/search — Search." in out
        assert "dify_tools" in out
        assert "mcp" in out.lower()
        assert "dify_tools" in out
        assert "mcp" in out.lower()

    def test_knowledge_retrieval_builder_requires_catalogue_dataset_ids(self):
        out = format_node_knowledge_catalogue_section("- id=dataset-1 name=Product Docs — Documentation.")

        assert "# Available knowledge bases" in out
        assert "dataset_ids" in out
        assert "exact" in out.lower()
        assert "id=dataset-1" in out


class TestNodeBuilderPrompt:
    def test_requires_user_visible_node_content_in_requested_language(self):
        prompt = get_node_builder_system_prompt("llm")

        assert "# Output language" in prompt
        assert "user-visible" in prompt

    def test_only_includes_target_node_schema_and_compact_output_contract(self):
        prompt = get_node_builder_system_prompt("llm")

        assert '"config"' in prompt
        assert "- llm:" in prompt
        assert "- if-else:" not in prompt
        assert '"viewport":' not in prompt
        assert '"positionAbsolute":' not in prompt

    def test_supports_main_human_input_and_assigner_contracts(self):
        human_input = get_node_builder_system_prompt("human-input")
        assigner = get_node_builder_system_prompt("assigner")

        assert "delivery_methods" in human_input
        assert "user_actions" in human_input
        assert '"version": "2"' in assigner
        assert "variable_selector" in assigner

    def test_documents_graphon_container_and_human_input_boundaries(self):
        human_input = get_node_builder_system_prompt("human-input")
        iteration = get_node_builder_system_prompt("iteration")
        loop = get_node_builder_system_prompt("loop")

        assert "^[A-Za-z_][A-Za-z0-9_]*$" in human_input
        assert "__timeout" in human_input
        assert '"id": "webapp"' not in human_input
        assert "generator supplies ``start_node_id``" in iteration
        assert "``parallel_nums`` must be at least 1" in iteration
        assert "generator supplies ``start_node_id``" in loop
        assert "``loop_count`` must be an integer from 1 to 100" in loop
        assert "``loop_variables`` must be a list" in loop
        assert "Each item must include ``value``" in loop

    def test_common_node_prompts_stay_small(self):
        sizes = [len(get_node_builder_system_prompt(node_type)) for node_type in ("start", "llm", "end")]

        assert max(sizes) < 3600

    def test_unknown_node_type_gets_minimal_fallback(self):
        prompt = get_node_builder_system_prompt("future-node")

        assert "future-node" in prompt
        assert "minimum valid config fields" in prompt

    def test_agent_v2_builder_snippet(self):
        prompt = get_node_builder_system_prompt("agent")

        assert "- agent" in prompt
        assert "Dify Agent Node v2" in prompt
        assert '"agent_node_kind": "dify_agent"' in prompt
        assert "Do NOT invent agent_id" in prompt

    def test_treats_purpose_as_spec_and_allows_provisional_outputs(self):
        prompt = get_node_builder_system_prompt("llm")

        assert "Purpose is the spec" in prompt
        assert "preserve its variable references" in prompt
        assert "provisional ones are same-batch" in prompt


class TestNodeBuilderUserSections:
    def test_formats_start_inputs(self):
        out = format_start_inputs_section(
            [{"variable": "url", "label": "URL", "type": "text-input"}, {"variable": "", "label": "Ignored"}]
        )

        assert "variable='url'" in out
        assert "type='text-input'" in out
        assert "Ignored" not in out

    def test_empty_start_inputs_are_omitted(self):
        assert format_start_inputs_section([]) == ""

    def test_parallel_plan_is_compact_and_preserves_topology(self):
        rendered = format_parallel_plan(
            [{"id": "node1", "node_type": "start"}, {"id": "node2", "node_type": "end"}],
            [{"source": "node1", "target": "node2"}],
        )

        assert " " not in rendered
        assert json.loads(rendered)["edges"] == [{"source": "node1", "target": "node2"}]
        assert "start_inputs" not in json.loads(rendered)

    def test_parallel_plan_carries_declared_start_inputs(self):
        rendered = format_parallel_plan(
            [{"id": "node1", "node_type": "start"}],
            [],
            [{"variable": "url", "label": "URL", "type": "text-input"}],
        )

        assert json.loads(rendered)["start_inputs"] == [{"variable": "url", "label": "URL", "type": "text-input"}]


class TestModeSection:
    def test_advanced_chat_documents_system_variables(self):
        out = format_mode_section("advanced-chat")

        assert "sys.query" in out
        assert '["sys", "query"]' in out
        assert "do NOT invent start-node variables" in out

    def test_workflow_mode_forbids_system_variables(self):
        out = format_mode_section("workflow")

        assert "NO automatic system variables" in out


class TestExistingGraphSection:
    def test_edge_lines_surface_branch_source_handles(self):
        out = format_existing_graph_section(
            {
                "nodes": [{"id": "node1", "data": {"type": "if-else", "title": "Branch"}}],
                "edges": [
                    {"source": "node1", "target": "node2", "sourceHandle": "case-uuid-1"},
                    {"source": "node2", "target": "node3", "sourceHandle": "source"},
                ],
            }
        )

        assert "- node1 -> node2 (source_handle='case-uuid-1')" in out
        assert "- node2 -> node3\n" in out
        assert "copy its source_handle verbatim" in out

    def test_create_mode_renders_nothing(self):
        assert format_existing_graph_section(None) == ""
