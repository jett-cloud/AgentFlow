from services.tool_plugin_generator.prompts import (
    build_agent_system_prompt,
    build_fill_prompt,
    infer_agent_mode,
)


def test_infer_agent_mode_first_tool_when_empty() -> None:
    assert infer_agent_mode(files_empty=True, intent=None, user_message="hi") == "first_tool"


def test_infer_agent_mode_add_tool_from_intent_or_text() -> None:
    assert (
        infer_agent_mode(files_empty=False, intent="add_tool", user_message="anything") == "add_nth_tool"
    )
    assert (
        infer_agent_mode(files_empty=False, intent=None, user_message="请新增工具 ping") == "add_nth_tool"
    )


def test_infer_agent_mode_edit_existing_default() -> None:
    assert infer_agent_mode(files_empty=False, intent=None, user_message="fix the timeout") == "edit_existing"


def test_build_agent_system_prompt_includes_mode_and_never_bootstrap_for_edit() -> None:
    prompt = build_agent_system_prompt(
        {
            "mode": "edit_existing",
            "author": "acme",
            "plugin_name": "demo",
            "plugin_identity_locked": True,
            "active_tool_name": "echo",
            "files_empty": False,
            "file_count": 2,
            "existing_tools": ["echo"],
            "tool_count": 1,
            "paths": ["manifest.yaml", "tools/echo.py"],
            "install_state": "dirty",
            "has_installation_id": True,
            "credentials_required": False,
            "last_validate": "ok",
            "last_test": "n/a",
            "iterations_left": 12,
        }
    )
    assert "mode: edit_existing" in prompt
    assert "Do not bootstrap_scaffold" in prompt
    assert "call validate" in prompt
    assert "Never claim it is installed" in prompt
    assert "verify_cycle" not in prompt
    assert "existing_tools: ['echo']" in prompt
    assert "image.blob" in prompt
    assert "create_blob_message" in prompt
    assert "extra: {python: {source: provider/<name>.py}}" in prompt
    assert "extra: {python: {source: tools/<tool>.py}}" in prompt
    assert "Urgent fix from last validate/test" not in prompt


def test_build_agent_system_prompt_emphasizes_file_api_after_fetch_file_failure() -> None:
    prompt = build_agent_system_prompt(
        {
            "mode": "edit_existing",
            "author": "ghy",
            "plugin_name": "remove-bg",
            "plugin_identity_locked": True,
            "active_tool_name": "remove_image_background",
            "files_empty": False,
            "file_count": 8,
            "existing_tools": ["remove_image_background"],
            "tool_count": 1,
            "paths": ["tools/remove_image_background.py"],
            "install_state": "dirty",
            "has_installation_id": True,
            "credentials_required": True,
            "last_validate": "ok",
            "last_test": "Failed to read file: 'RemoveImageBackgroundTool' object has no attribute 'fetch_file'",
            "iterations_left": 8,
        }
    )
    assert "Urgent fix from last validate/test" in prompt
    assert "Do NOT call `self.fetch_file`" in prompt


def test_build_fill_prompt_has_invoke_examples() -> None:
    prompt = build_fill_prompt(
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        user_prompt="echo text",
        api_doc="",
    )
    assert "Good example body" in prompt
    assert "Bad example" in prompt
