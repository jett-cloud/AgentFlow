from dataclasses import replace

from core.workflow.generator.agent.compaction import TokenLimits, assemble_prompt
from core.workflow.generator.agent.prompts import render_current_situation
from core.workflow.generator.agent.types import AgentMessage, AgentSession


def _limits(*, input_limit: int = 1000) -> TokenLimits:
    return TokenLimits(
        input_limit=input_limit,
        compact_trigger=int(input_limit * 0.8),
        compact_target=int(input_limit * 0.7),
        compactor_input_limit=400,
    )


def _session_with_config_node(*, message_count: int = 3) -> AgentSession:
    messages = [
        AgentMessage(
            sequence=1,
            event_type="message",
            role="user",
            status="completed",
            payload={"text": "做 RAG 测试工作流"},
        ),
        AgentMessage(
            sequence=2,
            event_type="tool_call",
            role="assistant",
            status="completed",
            payload={"id": "call_read", "name": "read_node", "arguments": {"id": "kr"}},
        ),
        AgentMessage(
            sequence=3,
            event_type="tool_result",
            role="assistant",
            status="completed",
            payload={
                "tool_call_id": "call_read",
                "name": "read_node",
                "content": {"id": "kr", "config": {"blob": "6000-token-config"}},
            },
        ),
        AgentMessage(
            sequence=4,
            event_type="tool_call",
            role="assistant",
            status="completed",
            payload={"id": "call_search", "name": "search_datasets", "arguments": {"query": "kb"}},
        ),
        AgentMessage(
            sequence=5,
            event_type="tool_result",
            role="assistant",
            status="completed",
            payload={"tool_call_id": "call_search", "name": "search_datasets", "content": {"hits": []}},
        ),
        AgentMessage(
            sequence=6,
            event_type="message",
            role="assistant",
            status="completed",
            payload={"text": "下一步校验"},
        ),
    ]
    graph = {
        "nodes": [
            {
                "id": "kr",
                "data": {
                    "type": "knowledge-retrieval",
                    "title": "检索",
                    "query_template": "secret-config-value",
                    "dataset_ids": ["ds-secret"],
                    "catalogue": "tenant-catalogue-must-not-leak",
                },
            },
            {
                "id": "start",
                "data": {"type": "start", "title": "开始"},
            },
        ],
        "edges": [{"source": "start", "target": "kr"}],
        "viewport": {"x": 0.0, "y": 0.0, "zoom": 0.7},
    }
    return AgentSession(
        messages=messages[:message_count] if message_count < len(messages) else messages,
        candidate_graph=graph,
        candidate_revision=3,
        candidate_base_hash="abc123",
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
    )


def test_current_situation_omits_node_config_and_catalogue() -> None:
    session = _session_with_config_node()
    text = render_current_situation(session)
    assert "secret-config-value" not in text
    assert "ds-secret" not in text
    assert "tenant-catalogue-must-not-leak" not in text
    assert "catalogue" not in text.lower()
    assert "kr" in text
    assert "knowledge-retrieval" in text
    assert "检索" in text
    assert "candidate_revision: 3" in text
    assert "# Current situation" in text


def test_current_situation_exposes_contract_and_durable_user_turn_ids() -> None:
    session = replace(
        _session_with_config_node(),
        contract_protocol_version=1,
        contract_revision=2,
        contract_hash="a" * 64,
        workflow_contract={
            "protocol_version": 1,
            "revision": 2,
            "contract_hash": "a" * 64,
            "status": "draft",
        },
    )

    text = render_current_situation(session)

    assert "workflow_contract: draft @2 (aaaaaaaaaaaa)" in text
    assert "user_turn_ids: turn:1" in text


def test_current_situation_marks_legacy_contract_protocol() -> None:
    text = render_current_situation(_session_with_config_node())

    assert "workflow_contract: legacy" in text


def test_current_situation_stays_at_tail_below_and_above_trigger() -> None:
    session = _session_with_config_node()
    situation = render_current_situation(session)

    below = assemble_prompt(
        session=session,
        situation_text=situation,
        system_text="system",
        limits=_limits(input_limit=10_000),
        token_counter=lambda msgs: 100,
        compact=None,
    )
    below_text = "\n".join(getattr(m, "content", "") or "" for m in below.messages)
    assert below_text.rstrip().endswith(situation.rstrip())
    assert "[COMPRESSED]" not in below_text

    def compact(*, compacted_state: dict | None, segment: list, **kwargs: object) -> dict[str, object]:
        return {
            "objective": ["构建 RAG 测试工作流"],
            "user_constraints": [],
            "confirmed_facts": [],
            "decisions": [],
            "rejected_approaches": [],
            "important_resources": [],
            "pending_work": [],
            "reloadable_details": [],
        }

    above = assemble_prompt(
        session=session,
        situation_text=situation,
        system_text="system",
        limits=_limits(input_limit=1000),
        token_counter=lambda msgs: (
            50 if any("[COMPACTED HISTORY]" in (getattr(m, "content", "") or "") for m in msgs) else 900
        ),
        compact=compact,
    )
    above_text = "\n".join(getattr(m, "content", "") or "" for m in above.messages)
    assert above_text.rstrip().endswith(situation.rstrip())
    assert "[COMPRESSED]" not in above_text


def test_last_finish_stays_none_when_only_validate_graph_passed() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=3,
        last_validation={"valid": True, "validated_revision": 3, "errors": []},
    )
    text = render_current_situation(session)
    assert "last_finish: none" in text
    assert "last_validation: ok @3" in text
    assert "last_acceptance: none" in text


def test_last_finish_is_success_only_after_accepted_finish() -> None:
    base = _session_with_config_node()
    session = replace(
        base,
        candidate_revision=3,
        last_validation={"valid": True, "validated_revision": 3, "errors": []},
        messages=[
            *base.messages,
            AgentMessage(
                sequence=7,
                event_type="tool_call",
                role="assistant",
                status="completed",
                payload={"id": "call_finish", "name": "finish", "arguments": {"summary": "完成"}},
            ),
            AgentMessage(
                sequence=8,
                event_type="tool_result",
                role="assistant",
                status="completed",
                payload={
                    "tool_call_id": "call_finish",
                    "name": "finish",
                    "ok": True,
                    "changed": False,
                    "content": {"valid": True, "errors": [], "summary": "完成"},
                    "error": None,
                    "error_code": None,
                    "retryable": False,
                },
            ),
        ],
    )
    text = render_current_situation(session)
    assert "last_finish: success (not applied)" in text
    assert "last_validation: ok @3" in text


def test_last_validation_error_label_includes_count_revision_and_codes() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=4,
        last_validation={
            "valid": False,
            "validated_revision": 4,
            "errors": [
                {"code": "MISSING_END", "node_id": "start", "detail": "no end"},
                {"code": "UNKNOWN_DATASET", "node_id": "kr", "detail": "bad ds"},
            ],
        },
    )
    text = render_current_situation(session)
    assert "last_validation: 2 errors @4 (MISSING_END@start, UNKNOWN_DATASET@kr)" in text
    assert "last_finish: none" in text
    assert "last_acceptance: none" in text


def test_last_acceptance_not_executed_label() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=66,
        last_acceptance={"passed": True, "revision": 66, "executed": False},
    )
    text = render_current_situation(session)
    assert "last_acceptance: not_executed @66" in text


def test_last_acceptance_failed_label_includes_nodes() -> None:
    session = replace(
        _session_with_config_node(),
        candidate_revision=4,
        last_acceptance={
            "passed": False,
            "revision": 4,
            "reason": "ASSERTION_FAILED",
            "failed_nodes": [{"id": "end", "type": "end", "error": "missing output"}],
        },
    )
    text = render_current_situation(session)
    assert "last_acceptance: 1 failed @4 (ASSERTION_FAILED) (end:missing output)" in text


def test_current_situation_lists_hard_bound_references_and_selected_node() -> None:
    session = replace(
        _session_with_config_node(),
        selected_node="n-drag",
        referenced_nodes=[{"id": "n1", "label": "知识库检索"}],
        referenced_tools=[{"id": "time/current_time", "label": "当前时间"}],
        referenced_datasets=[{"id": "ds-uuid", "label": "产品文档"}],
    )
    text = render_current_situation(session)
    assert "selected_node: n-drag" in text
    assert "referenced_nodes: n1 (知识库检索)" in text
    assert "referenced_tools: time/current_time (当前时间)" in text
    assert "referenced_datasets: ds-uuid (产品文档)" in text


def test_turn_complete_last_run_is_not_labeled_aborted() -> None:
    session = replace(_session_with_config_node(), last_run="turn_complete")
    text = render_current_situation(session)
    assert "last_run: turn_complete" in text
    assert "aborted" not in text


def test_system_prompt_hard_binds_referenced_ids() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT

    assert "referenced_nodes" in SYSTEM_PROMPT
    assert "referenced_tools" in SYSTEM_PROMPT
    assert "referenced_datasets" in SYSTEM_PROMPT
    assert "Use exact CurrentSituation ids" in SYSTEM_PROMPT
    assert "referenced_nodes identify existing nodes" in SYSTEM_PROMPT
    assert "referenced_nodes → `build_node`" not in SYSTEM_PROMPT
    assert "search_tools" in SYSTEM_PROMPT
    assert "search_datasets" in SYSTEM_PROMPT
    assert "ask_user" in SYSTEM_PROMPT
    assert "unexecuted_node_ids" in SYSTEM_PROMPT
    assert "business_verified" in SYSTEM_PROMPT
    assert "Plain text never finishes" not in SYSTEM_PROMPT
    assert "no tool_calls" in SYSTEM_PROMPT
    assert "<think>" in SYSTEM_PROMPT
    assert "JSON belongs in tool_calls" in SYSTEM_PROMPT
    assert "activate_skills" in SYSTEM_PROMPT
    assert "skill selection" in SYSTEM_PROMPT
    assert "submit_workflow_plan" in SYSTEM_PROMPT
    assert "expected_revision" in SYSTEM_PROMPT
    assert "user_turn_ids" in SYSTEM_PROMPT


def test_system_prompt_routes_configuration_details_to_authoritative_schemas() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT

    for required in (
        "structured semantic intent",
        "public builder argument schema",
        "inspect_node_schema",
        "search_tools",
        "inspect_tool",
        "build_tool_node",
        "build_agent_node",
        "tools/mcp_tools/knowledge",
        "selector",
        "omission/replacement/clearing",
    ):
        assert required in SYSTEM_PROMPT
    assert '["iteration_id", "item", "source_image"]' not in SYSTEM_PROMPT
    assert "Builder writes the binding" not in SYSTEM_PROMPT
    assert "# build_node purpose contract" not in SYSTEM_PROMPT
    assert "Resource bindings:" not in SYSTEM_PROMPT


def test_agent_internal_knowledge_routes_through_specialized_builder() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT
    from core.workflow.generator.compiler.intents.agent_intent import AgentNodeBuildIntent
    from core.workflow.generator.prompts.loader import read_node_snippet, skill_body

    binding_skill = skill_body("bind-resources") or ""
    agent_node_spec = read_node_snippet("agent")
    intent = AgentNodeBuildIntent.model_validate(
        {
            "model": {"provider": "openai", "name": "gpt-4o"},
            "instruction": "Answer from product docs",
            "inputs": [],
            "outputs": [],
            "knowledge": {
                "operation": "replace",
                "sets": [{"name": "Product docs", "dataset_ids": ["ds-1"]}],
            },
        }
    )

    assert "tools/mcp_tools/knowledge" in SYSTEM_PROMPT
    assert "Agent-internal knowledge belongs in build_agent_node knowledge" in SYSTEM_PROMPT
    assert "standalone knowledge-retrieval" in SYSTEM_PROMPT
    assert 'knowledge={"operation":"replace"' in binding_skill
    assert "do not connect a separate retrieval edge" in binding_skill
    assert 'requirements=["dataset_ids=' not in binding_skill
    assert "Do not emit knowledge" in agent_node_spec
    assert intent.knowledge is not None
    assert intent.knowledge.sets[0].dataset_ids == ["ds-1"]


def test_system_prompt_encourages_batched_creates() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT
    from core.workflow.generator.prompts.loader import skill_body

    playbook = skill_body("create-from-scratch") or ""
    combined = f"{SYSTEM_PROMPT}\n{playbook}"
    assert "必须" not in combined
    assert "Independent creates may share" in playbook
    assert "build_node(mode=create)" in playbook
    assert "native multi-tool" in playbook
    assert "verify-and-finish" in playbook
    assert "retry create with the same intended ID" in SYSTEM_PROMPT
    assert "producer-first" in SYSTEM_PROMPT
    assert "submit the consumer in the next invocation" in SYSTEM_PROMPT
    assert "Free-text references are not scheduling facts" in SYSTEM_PROMPT


def test_system_prompt_distinguishes_recovery_from_retryability_and_completion() -> None:
    from core.workflow.generator.agent.loop import SYSTEM_PROMPT

    for rule in (
        "a rejection can carry these reports without an error_code",
        "retryable controls retry/cascade behavior",
        "it does not decide whether to ask a user",
        "Respect runtime cancellation and exhausted budgets",
        "question id live_run_consent",
        "Contract and graph revisions are independent",
        "passing graph/contract checks",
        "Finish does not Apply",
        "runtime_contract_passed",
        "business_verified",
    ):
        assert rule in SYSTEM_PROMPT
    assert "A retryable tool error is not a reason to call fail or ask_user" not in SYSTEM_PROMPT


def test_workflow_assist_builder_specs_require_node_specific_semantic_fields() -> None:
    from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent, render_node_builder_spec

    intent = NodeBuildIntent(objective="Build the requested node")
    expected_fields = {
        "llm": ("prompt_template", "model.provider", "model.name"),
        "http-request": ("url",),
        "if-else": ("cases",),
        "question-classifier": ("query_variable_selector", "classes", "model.provider", "model.name"),
        "parameter-extractor": ("query", "parameters", "model.provider", "model.name"),
        "human-input": ("form_content", "delivery_methods", "user_actions"),
    }

    for node_type, fields in expected_fields.items():
        rendered = render_node_builder_spec(intent, node_type=node_type)
        for field in fields:
            assert field in rendered
        assert "Runtime schema defaults do not make an empty semantic field complete" in rendered


def test_repair_validation_skill_explains_invalid_node_config_field_repair() -> None:
    from core.workflow.generator.prompts.loader import skill_body

    repair = skill_body("repair-validation") or ""

    assert "INVALID_NODE_CONFIG" in repair
    assert "field path" in repair
    assert "read_node" in repair
    assert "resubmit build_node" in repair
    assert "Do not patch raw node JSON" in repair
    assert "Document Extractor" in repair
    assert "file-list" in repair
    assert "variable_selector" in repair
    assert "activate verify-and-finish" in repair


def _user_message(sequence: int, text: str) -> AgentMessage:
    return AgentMessage(
        sequence=sequence,
        event_type="message",
        role="user",
        status="completed",
        payload={"text": text},
    )


def _activate_pair(sequence: int, names: list[str], *, ok: bool = True) -> list[AgentMessage]:
    call_id = f"act-{sequence}"
    call = AgentMessage(
        sequence=sequence,
        event_type="tool_call",
        role="assistant",
        status="completed",
        payload={"id": call_id, "name": "activate_skills", "arguments": {"names": names}},
    )
    result = AgentMessage(
        sequence=sequence + 1,
        event_type="tool_result",
        role="assistant",
        status="completed",
        payload={
            "tool_call_id": call_id,
            "name": "activate_skills",
            "ok": ok,
            "changed": False,
            "content": {"active_skills": names} if ok else None,
            "error_code": None if ok else "UNKNOWN_SKILL",
        },
    )
    return [call, result]


def test_active_skills_default_none_in_current_situation() -> None:
    text = render_current_situation(_session_with_config_node())
    assert "active_skills: none" in text


def test_active_skill_names_uses_latest_successful_activation() -> None:
    from core.workflow.generator.agent.prompts import active_skill_names

    session = replace(
        _session_with_config_node(),
        messages=[
            _user_message(1, "做 RAG 测试工作流"),
            *_activate_pair(2, ["create-from-scratch"]),
            *_activate_pair(4, ["repair-validation", "bind-resources"]),
        ],
    )
    assert active_skill_names(session) == ("repair-validation", "bind-resources")
    text = render_current_situation(session)
    assert "active_skills: repair-validation, bind-resources" in text


def test_failed_activation_does_not_replace_active_skills() -> None:
    from core.workflow.generator.agent.prompts import active_skill_names

    session = replace(
        _session_with_config_node(),
        messages=[
            _user_message(1, "做 RAG 测试工作流"),
            *_activate_pair(2, ["create-from-scratch"]),
            *_activate_pair(4, ["not-a-skill"], ok=False),
        ],
    )
    assert active_skill_names(session) == ("create-from-scratch",)


def test_new_user_message_resets_active_skills() -> None:
    from core.workflow.generator.agent.prompts import active_skill_names

    session = replace(
        _session_with_config_node(),
        messages=[
            _user_message(1, "先建图"),
            *_activate_pair(2, ["create-from-scratch"]),
            _user_message(4, "改成检索"),
        ],
    )
    assert active_skill_names(session) == ()


def test_ask_user_answer_does_not_reset_active_skills() -> None:
    from core.workflow.generator.agent.prompts import active_skill_names

    session = replace(
        _session_with_config_node(),
        messages=[
            _user_message(1, "做 RAG 测试工作流"),
            *_activate_pair(2, ["edit-local-node"]),
            AgentMessage(
                sequence=4,
                event_type="tool_call",
                role="assistant",
                status="completed",
                payload={
                    "id": "ask-1",
                    "name": "ask_user",
                    "arguments": {"questions": [{"id": "q1", "question": "哪个节点", "kind": "text"}]},
                },
            ),
            AgentMessage(
                sequence=5,
                event_type="tool_result",
                role="assistant",
                status="completed",
                payload={"tool_call_id": "ask-1", "name": "ask_user", "ok": True, "content": {"text": "检索节点"}},
            ),
        ],
    )
    assert active_skill_names(session) == ("edit-local-node",)


def test_deleted_historical_skills_are_filtered() -> None:
    from core.workflow.generator.agent.prompts import active_skill_names

    session = replace(
        _session_with_config_node(),
        messages=[
            _user_message(1, "做 RAG 测试工作流"),
            *_activate_pair(2, ["create-from-scratch", "retired-skill"]),
        ],
    )
    assert active_skill_names(session) == ("create-from-scratch",)


def test_render_active_skills_keeps_activation_order() -> None:
    from core.workflow.generator.agent.prompts import render_active_skills

    text = render_active_skills(("create-from-scratch", "bind-resources"))
    assert text.startswith("# Active skills")
    create_at = text.index("## create-from-scratch")
    bind_at = text.index("## bind-resources")
    assert create_at < bind_at
    assert "read_graph" in text
    assert "referenced_tools" in text
    assert render_active_skills(()) == ""
