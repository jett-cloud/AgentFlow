import pytest

from services.tool_plugin_generator.candidate_builder import prepare_candidate_source
from services.tool_plugin_generator.preflight import ToolPluginPreflightError


def _files() -> dict[str, str]:
    return {
        "manifest.yaml": "version: 0.0.1\nauthor: acme\nname: demo\n",
        "main.py": "from dify_plugin import Plugin\nplugin = Plugin()\n",
        "requirements.txt": "dify_plugin>=0.0.1b70,<0.1.0\n",
        "README.md": "# Demo\n",
        "_assets/icon.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>\n",
        "provider/demo.yaml": "identity:\n  name: demo\n",
        "provider/demo.py": "from dify_plugin import ToolProvider\nclass DemoProvider(ToolProvider):\n    pass\n",
        "tools/echo.yaml": "identity:\n  name: echo\nparameters: []\n",
        "tools/echo.py": "from dify_plugin import Tool\nclass EchoTool(Tool):\n    pass\n",
    }


def test_prepare_candidate_validates_and_previews_one_canonical_snapshot() -> None:
    result = prepare_candidate_source(
        _files(),
        author="acme",
        plugin_name="demo",
        tool_name="echo",
    )

    assert result.draft_digest != result.canonical_digest
    assert result.canonical_files["requirements.txt"] == "dify-plugin>=0.9.0,<0.10.0\n"
    assert "Plugin(DifyPluginEnv())" in result.canonical_files["main.py"]
    assert result.preview is not None
    assert result.preview["tool_name"] == "echo"


def test_prepare_candidate_is_stable_for_already_canonical_source() -> None:
    first = prepare_candidate_source(_files())
    second = prepare_candidate_source(first.canonical_files)

    assert first.canonical_files == second.canonical_files
    assert first.canonical_digest == second.canonical_digest
    assert second.draft_digest == second.canonical_digest


def test_preflight_failure_keeps_draft_and_canonical_trace() -> None:
    files = _files()
    files["tools/echo.py"] = "from dify_plugin.errors.tool import ToolInvokeError\n"

    with pytest.raises(ToolPluginPreflightError) as exc_info:
        prepare_candidate_source(files)

    trace = exc_info.value.build_trace()
    assert trace is not None
    assert len(trace["draft_digest"]) == 64
    assert len(trace["canonical_digest"]) == 64
    assert trace["completed_stages"] == ["canonicalize", "preflight"]
