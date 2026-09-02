import ast

from services.tool_plugin_generator.scaffold import ToolPluginFill, render_scaffold
from services.tool_plugin_generator.validator import validate_plugin_files


def test_render_scaffold_includes_required_paths():
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
    assert "manifest.yaml" in files
    assert "provider/demo.yaml" in files
    assert "tools/echo.yaml" in files
    assert "tools/echo.py" in files
    assert "_assets/icon.svg" in files
    # CLI resolves icons by filename under `_assets/`; path prefixes fail packaging.
    assert "icon: icon.svg" in files["manifest.yaml"]
    assert "icon: icon.svg" in files["provider/demo.yaml"]
    assert "icon: icon.svg" in files["tools/echo.yaml"]
    assert "_assets/icon.svg" not in files["manifest.yaml"]
    assert "dify-plugin>=0.9.0,<0.10.0" in files["requirements.txt"]
    assert "dify-plugin>=0.0.1,<0.1.0" not in files["requirements.txt"]
    assert "dify-plugin>=0.9.0,<1.0.0" not in files["requirements.txt"]


def test_render_scaffold_keeps_multiline_invoke_body_parseable():
    fill = ToolPluginFill(
        provider_label="Demo",
        tool_label="Echo",
        tool_description="echo",
        parameters=[],
        credentials=[],
        invoke_python_body=(
            "text = tool_parameters.get('text', '')\n"
            "if text:\n"
            "    yield self.create_text_message(text)\n"
            "else:\n"
            "    yield self.create_text_message('empty')\n"
        ),
        readme="# Demo",
    )
    files = render_scaffold(author="acme", plugin_name="demo", tool_name="echo", fill=fill)
    ast.parse(files["tools/echo.py"])
    validate_plugin_files(files)
