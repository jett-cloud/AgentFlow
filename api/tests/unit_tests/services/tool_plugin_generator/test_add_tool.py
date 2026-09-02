import pytest

from services.tool_plugin_generator.scaffold import ToolPluginFill, add_tool_to_plugin, render_scaffold


def test_add_tool_to_plugin_merges_second_tool() -> None:
    fill = ToolPluginFill(
        provider_label="Demo",
        tool_label="Echo",
        tool_description="echo",
        parameters=[],
        credentials=[],
        invoke_python_body='yield self.create_text_message("ok")',
        readme="# Demo",
    )
    files = render_scaffold(author="acme", plugin_name="demo", tool_name="echo", fill=fill)
    second = ToolPluginFill(
        provider_label="Demo",
        tool_label="Ping",
        tool_description="ping",
        parameters=[{"name": "host", "type": "string", "required": True, "label": "Host"}],
        credentials=[],
        invoke_python_body='yield self.create_text_message("pong")',
        readme="",
    )
    updated = add_tool_to_plugin(
        files,
        author="acme",
        plugin_name="demo",
        tool_name="ping",
        fill=second,
    )
    assert "tools/ping.yaml" in updated
    assert "tools/ping.py" in updated
    assert "tools/echo.yaml" in updated
    provider = updated["provider/demo.yaml"]
    assert "tools/echo.yaml" in provider
    assert "tools/ping.yaml" in provider


def test_add_tool_rejects_duplicate_name() -> None:
    fill = ToolPluginFill(
        provider_label="Demo",
        tool_label="Echo",
        tool_description="echo",
        parameters=[],
        credentials=[],
        invoke_python_body='yield self.create_text_message("ok")',
        readme="# Demo",
    )
    files = render_scaffold(author="acme", plugin_name="demo", tool_name="echo", fill=fill)
    with pytest.raises(ValueError, match="already exists"):
        add_tool_to_plugin(files, author="acme", plugin_name="demo", tool_name="echo", fill=fill)
