from services.workflow_assist.run_values import project_sse_event_payload


def test_tool_call_projects_server_owned_display_text() -> None:
    projected = project_sse_event_payload(
        "tool_call",
        {"id": "call-1", "name": "run_workflow", "arguments": {}},
    )

    assert projected["name"] == "run_workflow"
    assert projected["display"] == {"visible": True, "text": "正在试运行工作流…"}


def test_internal_tool_is_hidden_by_server_presentation() -> None:
    projected = project_sse_event_payload(
        "tool_call",
        {"id": "call-1", "name": "activate_skills", "arguments": {"names": ["editing"]}},
    )

    assert projected["display"] == {"visible": False}


def test_finish_result_uses_short_display_and_keeps_summary_for_done_only() -> None:
    projected = project_sse_event_payload(
        "tool_result",
        {
            "id": "call-1",
            "name": "finish",
            "ok": True,
            "summary": "这是一段不应该出现在执行步骤中的很长总结",
        },
    )

    assert projected["display"] == {"visible": True, "text": "工作流校验通过"}
    assert "summary" not in projected


def test_unknown_tool_never_exposes_internal_name_as_display_text() -> None:
    projected = project_sse_event_payload(
        "tool_result",
        {"id": "call-1", "name": "new_internal_method", "ok": True, "summary": "ok"},
    )

    assert projected["display"] == {"visible": True, "text": "处理完成"}
