"""Markdown prompt loader and skill registry."""

from pathlib import Path

import pytest

from core.workflow.generator.prompts.builder_prompts import get_node_config_snippet
from core.workflow.generator.prompts.loader import (
    ALWAYS_ON_CHAR_LIMIT,
    always_on_system_prompt,
    available_node_types,
    load_skill_records,
    node_config_snippets,
    read_frontmatter,
    read_prompt,
    render_skill_catalogue,
    skill_body,
    skill_summaries,
)
from core.workflow.generator.prompts.planner_prompts import PLANNER_SYSTEM_PROMPT


def test_read_prompt_returns_empty_for_missing_file() -> None:
    assert read_prompt("nodes/does-not-exist.md") == ""


def test_read_prompt_strips_yaml_frontmatter() -> None:
    body = read_prompt("agent/skills/create-from-scratch/SKILL.md")
    assert not body.startswith("---")
    assert "read_graph" in body
    meta = read_frontmatter("agent/skills/create-from-scratch/SKILL.md")
    assert meta["name"] == "create-from-scratch"
    assert "description" in meta


def test_unknown_node_snippet_is_empty() -> None:
    assert get_node_config_snippet("future-node") == ""


def test_llm_snippet_keeps_prompt_template_and_placeholder_rules() -> None:
    snippet = get_node_config_snippet("llm")
    assert "prompt_template" in snippet
    assert "{{#node.var#}}" in snippet


def test_agent_snippet_declares_default_outputs() -> None:
    snippet = get_node_config_snippet("agent")
    assert "agent_declared_outputs" in snippet
    assert "Outputs:" in snippet
    assert "text" in snippet


def test_start_snippet_documents_checkbox_and_canonical_json_object() -> None:
    snippet = get_node_config_snippet("start")

    assert '"type": "checkbox"' in snippet
    assert '"type": "json_object"' in snippet
    assert "never use ``json-object``" in snippet


def test_document_extractor_snippet_uses_graphon_runtime_cardinality() -> None:
    snippet = get_node_config_snippet("document-extractor")

    assert "file-list" in snippet
    assert "actual input" in snippet
    assert "do not emit the legacy ``is_array_file`` field" in snippet


def test_end_snippet_requires_outputs_and_lists_every_graphon_value_type() -> None:
    snippet = get_node_config_snippet("end")

    assert "at least one output" in snippet
    assert "``secret``" in snippet
    assert "Downstream cannot reference an end node" in snippet
    assert "must not have outgoing edges" in snippet


def test_answer_snippet_distinguishes_selectable_outputs_from_control_flow() -> None:
    snippet = get_node_config_snippet("answer")

    assert "non-blank" in snippet
    assert "Selectable outputs: none" in snippet
    assert "may continue to downstream nodes" in snippet


_PLANNER_NODE_TYPES = (
    "start",
    "end",
    "answer",
    "llm",
    "knowledge-retrieval",
    "code",
    "template-transform",
    "http-request",
    "tool",
    "agent",
    "if-else",
    "iteration",
    "loop",
    "question-classifier",
    "parameter-extractor",
    "document-extractor",
    "variable-aggregator",
    "list-operator",
    "assigner",
    "human-input",
)


def test_every_planner_node_type_has_a_snippet() -> None:
    node_config_snippets.cache_clear()
    for node_type in _PLANNER_NODE_TYPES:
        snippet = get_node_config_snippet(node_type)
        assert snippet, f"missing nodes.md section for {node_type}"
        assert f"- {node_type}" in snippet


def test_knowledge_retrieval_snippet_describes_all_retrieval_modes() -> None:
    node_config_snippets.cache_clear()
    snippet = get_node_config_snippet("knowledge-retrieval")

    assert "query_variable_selector" in snippet
    assert "query_attachment_selector" in snippet
    assert "single_retrieval_config" in snippet
    assert "reranking_model" in snippet
    assert "weighted_score" in snippet
    assert "weights" in snippet
    assert "metadata_filtering_mode" in snippet
    assert "result" in snippet


def test_code_snippet_declares_saved_contract() -> None:
    node_config_snippets.cache_clear()
    snippet = get_node_config_snippet("code")

    assert "non-empty" in snippet
    assert "value_selector" in snippet
    assert "at least two" in snippet
    assert "^[A-Za-z_][A-Za-z0-9_]*$" in snippet
    assert "unique" in snippet
    assert '"outputs": {}' in snippet
    assert "legal when the code returns no declared values" in snippet


def test_template_transform_snippet_declares_saved_contract() -> None:
    node_config_snippets.cache_clear()
    snippet = get_node_config_snippet("template-transform")

    assert "non-empty" in snippet
    assert "^[A-Za-z_][A-Za-z0-9_]*$" in snippet
    assert "30" in snippet
    assert "unique" in snippet
    assert "at least two" in snippet
    assert "non-empty strings" in snippet
    assert "{{ variable }}" in snippet
    assert "Outputs: output" in snippet


def test_human_input_snippet_declares_saved_contract() -> None:
    snippet = get_node_config_snippet("human-input")
    planner = PLANNER_SYSTEM_PROMPT
    assert "include_bound_group" in snippet
    assert "reference_id" in snippet
    assert "paragraph" in snippet
    assert "file-list" in snippet
    assert "^[A-Za-z_][A-Za-z0-9_]*$" in snippet
    assert "__timeout" in snippet
    assert "__action_id" in snippet
    assert "Do not emit ``_targetBranches``" in snippet
    assert "timeout ``3 day``" in snippet
    assert "36 hour" in snippet
    assert "invent member IDs" in snippet
    assert "Slack" in snippet
    assert "Trigger workflows cannot use WebApp" in snippet
    assert "Do not invent Email recipients" in planner
    assert "_targetBranches" in planner


def test_iteration_and_loop_snippets_document_child_scope() -> None:
    iteration = get_node_config_snippet("iteration")
    loop = get_node_config_snippet("loop")
    assert "Outputs:" in iteration
    assert '["<iter-id>", "item"]' in iteration
    assert "index" in iteration
    assert "Outputs:" in loop
    assert "loop_variables" in loop


def test_iteration_prompt_marks_internal_and_derived_fields_as_system_owned() -> None:
    snippet = get_node_config_snippet("iteration")
    assert "iteration-start" in snippet
    assert "must not emit" in snippet
    assert "iterator_input_type" in snippet
    assert "output_type" in snippet


def test_loop_prompt_marks_internal_fields_as_system_owned() -> None:
    snippet = get_node_config_snippet("loop")
    assert "loop-start" in snippet
    assert "must not emit" in snippet
    assert "error_handle_mode" in snippet
    assert "1 to 100" in snippet


def test_llm_and_http_snippets_declare_outputs() -> None:
    snippet = get_node_config_snippet("llm")
    assert "``text``" in snippet
    assert "``reasoning_content``" in snippet
    assert "``usage``" in snippet
    assert "``structured_output``" in snippet
    http = get_node_config_snippet("http-request")
    assert "Outputs:" in http
    assert "body" in http
    assert "status_code" in http


def test_http_request_snippet_declares_runtime_shape_and_acceptance_rules() -> None:
    snippet = get_node_config_snippet("http-request")

    assert "URL must be non-empty" in snippet
    assert "options" in snippet
    assert "api-key" in snippet
    assert '"type":"text"' in snippet
    assert '"connect"' in snippet
    assert "simulate_always" in snippet


def test_tool_snippet_requires_catalogue_identity_and_typed_parameters() -> None:
    snippet = get_node_config_snippet("tool")
    assert "exact value from catalogue" in snippet
    assert '"mixed"' in snippet
    assert '"variable"' in snippet
    assert '"constant"' in snippet
    assert "Do not invent output names" in snippet
    assert "metered" in snippet
    assert "inspect_tool" in snippet


def test_node_snippets_are_isolated_sections() -> None:
    if_else = get_node_config_snippet("if-else")
    llm = get_node_config_snippet("llm")
    assert "case_id" in if_else
    assert "prompt_template" not in if_else
    assert "prompt_template" in llm
    assert "case_id" not in llm


def test_if_else_snippet_declares_official_cases_and_implicit_else_contract() -> None:
    snippet = get_node_config_snippet("if-else")

    assert '"varType": "<Dify variable type>"' in snippet
    assert "ELSE is implicit" in snippet
    assert "must not be `false`" in snippet
    assert "Do not emit" in snippet
    assert "_targetBranches" in snippet
    assert "is null" in snippet
    assert "Graphon" not in snippet


def test_skill_registry_contains_required_skills_sorted_by_name() -> None:
    names = [item["name"] for item in skill_summaries()]
    assert names == sorted(names)
    assert {
        "bind-resources",
        "build-container",
        "verify-and-finish",
        "create-from-scratch",
        "edit-local-node",
        "repair-validation",
    }.issubset(names)


def test_load_skill_records_discovers_multiple_skills_sorted_by_name(tmp_path: Path) -> None:
    for name in ("zeta-skill", "alpha-skill"):
        skill_dir = tmp_path / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name} description.\n---\n\n# {name}\n",
            encoding="utf-8",
        )

    records = load_skill_records(tmp_path)

    assert [record["name"] for record in records] == ["alpha-skill", "zeta-skill"]


def test_skill_summaries_use_frontmatter_descriptions() -> None:
    descriptions = {item["name"]: item["description"] for item in skill_summaries()}
    for name, description in descriptions.items():
        meta = read_frontmatter(f"agent/skills/{name}/SKILL.md")
        assert description == str(meta["description"]).strip()
        assert description


def test_skill_name_must_match_directory(tmp_path: Path) -> None:
    skill_dir = tmp_path / "create-from-scratch"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: other-name\ndescription: A skill.\n---\n\n# Body\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must equal directory name"):
        load_skill_records(tmp_path)


def test_skill_missing_description_raises(tmp_path: Path) -> None:
    skill_dir = tmp_path / "create-from-scratch"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: create-from-scratch\n---\n\n# Body\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing a description"):
        load_skill_records(tmp_path)


def test_skill_missing_body_raises(tmp_path: Path) -> None:
    skill_dir = tmp_path / "create-from-scratch"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: create-from-scratch\ndescription: Build a graph.\n---\n\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing a body"):
        load_skill_records(tmp_path)


def test_duplicate_skill_names_raise(tmp_path: Path) -> None:
    first = tmp_path / "group-a" / "shared"
    second = tmp_path / "group-b" / "shared"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    content = "---\nname: shared\ndescription: Shared skill.\n---\n\n# Body\n"
    (first / "SKILL.md").write_text(content, encoding="utf-8")
    (second / "SKILL.md").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate skill name"):
        load_skill_records(tmp_path)


def test_repair_validation_skill_distinguishes_create_update_replace() -> None:
    body = skill_body("repair-validation") or ""
    assert "retry create with the same ID" in body
    assert "NODE_EXISTS instead requires read_node" in body
    assert "retry update" in body
    assert "retry replace" in body
    assert "read_node on every listed node_id" not in body


def test_skill_body_rejects_path_traversal() -> None:
    assert skill_body("../SYSTEM.md") is None
    assert skill_body("agent/skills/create-from-scratch/SKILL.md") is None
    assert skill_body("..\\create-from-scratch") is None
    body = skill_body("create-from-scratch")
    assert body is not None
    assert "read_graph" in body


def test_skill_catalogue_is_names_and_descriptions_only() -> None:
    text = render_skill_catalogue()
    assert text.startswith("# Available skills")
    assert "create-from-scratch" in text
    assert "bind-resources" in text
    assert "# Create from scratch" not in text
    assert "read_graph to confirm" not in text
    for item in skill_summaries():
        assert f"- {item['name']}: {item['description']}" in text


def test_always_on_system_routes_specialized_build_tools() -> None:
    text = always_on_system_prompt()
    assert "build_tool_node" in text
    assert "build_agent_node" in text
    assert "build_loop" in text
    assert "build_iteration" in text
    assert "build_node(type=tool" not in text
    assert "build_node(type=agent" not in text


def test_always_on_system_stays_under_char_limit() -> None:
    text = always_on_system_prompt()
    assert "referenced_nodes" in text
    assert "referenced_tools" in text
    assert "referenced_datasets" in text
    assert "`build_tool_node`" in text
    assert "`build_agent_node`" in text
    assert "create-from-scratch" in text
    assert "repair-validation" in text
    assert "# Available skills" in text
    assert "# Playbooks" not in text
    assert "# Available node types" in text
    assert "knowledge-retrieval" in text
    assert len(text) < ALWAYS_ON_CHAR_LIMIT
    for heading in (
        "# 1. Responsibilities and authoritative facts",
        "# 2. Tool calls and skill selection",
        "# 3. Workflow contract gate",
        "# 4. Construction contract",
        "# 5. Recovery and stopping",
        "# 6. Validation, acceptance, and completion",
    ):
        assert heading in text


def test_available_node_types_follow_nodes_md_headings() -> None:
    names = available_node_types()
    assert names[0] == "start"
    assert "llm" in names
    assert "human-input" in names
    assert "loop" in names
