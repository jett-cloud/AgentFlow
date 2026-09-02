"""Markdown prompt loader and playbook selection."""

from dataclasses import replace

from core.workflow.generator.agent.graph_ops import empty_graph
from core.workflow.generator.agent.prompts import render_active_skill, select_playbook
from core.workflow.generator.agent.types import AgentSession
from core.workflow.generator.prompts.builder_prompts import get_node_config_snippet
from core.workflow.generator.prompts.loader import (
    ALWAYS_ON_CHAR_LIMIT,
    always_on_system_prompt,
    read_frontmatter,
    read_prompt,
)


def _session(**overrides: object) -> AgentSession:
    base = AgentSession(
        messages=[],
        candidate_graph=empty_graph(),
        candidate_revision=0,
        candidate_base_hash=None,
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
        edit_mode="rebuild",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


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


def test_node_snippets_are_isolated_sections() -> None:
    if_else = get_node_config_snippet("if-else")
    llm = get_node_config_snippet("llm")
    assert "case_id" in if_else
    assert "prompt_template" not in if_else
    assert "prompt_template" in llm
    assert "case_id" not in llm


def test_select_playbook_prefers_bound_resources() -> None:
    session = _session(
        referenced_tools=[{"id": "time/current_time"}],
        last_validation={"valid": False, "errors": [{"code": "MISSING_END", "node_id": "start"}]},
        selected_node="n1",
        candidate_graph={"nodes": [{"id": "n1", "data": {"type": "llm"}}], "edges": []},
    )
    assert select_playbook(session) == "bind-resources"


def test_select_playbook_prefers_repair_over_local_edit() -> None:
    session = _session(
        last_validation={"valid": False, "errors": [{"code": "MISSING_END", "node_id": "start"}]},
        selected_node="n1",
        edit_mode="local",
        candidate_graph={"nodes": [{"id": "n1", "data": {"type": "llm"}}], "edges": []},
    )
    assert select_playbook(session) == "repair-validation"


def test_select_playbook_repairs_failed_acceptance() -> None:
    session = _session(
        last_acceptance={"passed": False, "reason": "ASSERTION_FAILED", "revision": 1},
        selected_node="n1",
        edit_mode="local",
        candidate_graph={"nodes": [{"id": "n1", "data": {"type": "llm"}}], "edges": []},
    )
    assert select_playbook(session) == "repair-validation"


def test_select_playbook_does_not_repair_live_consent_wait() -> None:
    session = _session(
        last_acceptance={"passed": None, "reason": "LIVE_RUN_REQUIRES_CONSENT", "revision": 1},
        selected_node="n1",
        edit_mode="local",
        candidate_graph={"nodes": [{"id": "n1", "data": {"type": "llm"}}], "edges": []},
    )
    assert select_playbook(session) == "edit-local-node"


def test_select_playbook_uses_local_edit_when_graph_has_nodes() -> None:
    session = _session(
        edit_mode="local",
        candidate_graph={"nodes": [{"id": "n1", "data": {"type": "llm"}}], "edges": []},
    )
    assert select_playbook(session) == "edit-local-node"


def test_select_playbook_defaults_to_create_on_empty_graph() -> None:
    session = _session(edit_mode="local")
    assert select_playbook(session) == "create-from-scratch"


def test_render_active_skill_includes_name_and_body() -> None:
    text = render_active_skill("repair-validation")
    assert "repair-validation" in text
    assert "validate_graph" in text
    assert "finish" in text


def test_always_on_system_stays_under_char_limit() -> None:
    text = always_on_system_prompt()
    assert "referenced_nodes" in text
    assert "build_node must use those exact ids" in text
    assert "create-from-scratch" in text
    assert "repair-validation" in text
    assert len(text) < ALWAYS_ON_CHAR_LIMIT
