import pytest

from services.tool_plugin_generator.validator import ToolPluginValidationError, validate_plugin_files


def _base_files(*, tool_py: str) -> dict[str, str]:
    return {
        "manifest.yaml": "version: 0.0.1\n",
        "main.py": "pass\n",
        "requirements.txt": "",
        "README.md": "# Demo\n",
        "tools/x.yaml": "identity:\n  name: x\nparameters:\n  - name: q\n    type: string\n    form: llm\n",
        "tools/x.py": tool_py,
    }


def test_validator_rejects_missing_manifest():
    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files({"main.py": "print(1)"})
    assert any("manifest" in error.lower() for error in exc_info.value.errors)


def test_validator_rejects_os_system():
    files = _base_files(tool_py="import os\nos.system('rm -rf /')\n")
    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files)
    assert any("os.system" in error or "forbidden" in error.lower() for error in exc_info.value.errors)


def test_validator_requires_tool_python_and_valid_syntax():
    files = {
        "manifest.yaml": "version: 0.0.1\n",
        "main.py": "pass\n",
        "requirements.txt": "",
        "README.md": "# Demo\n",
        "tools/echo.yaml": "identity:\n  name: echo\n",
    }
    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files)
    assert any("tools/echo.py" in error for error in exc_info.value.errors)

    files["tools/echo.py"] = "def broken(:\n"
    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files)
    assert any("syntax" in error.lower() for error in exc_info.value.errors)


def test_validator_rejects_fetch_file_with_remediation():
    files = _base_files(tool_py="data = self.fetch_file(tool_parameters['image_file'])\n")
    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files)
    joined = " ".join(exc_info.value.errors)
    assert "self.fetch_file" in joined
    assert ".blob" in joined


def test_validator_rejects_session_http_and_image_blob_message():
    files = _base_files(
        tool_py=(
            "self.session.post('https://example.com')\n"
            "yield self.create_image_message(blob=b'x', meta={'mime_type': 'image/png'})\n"
        )
    )
    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files)
    joined = " ".join(exc_info.value.errors)
    assert "self.session.post" in joined
    assert "httpx" in joined
    assert "create_image_message(blob=" in joined
    assert "create_blob_message" in joined


def test_validator_rejects_non_object_yaml_root():
    files = _base_files(tool_py="pass\n")
    files["tools/x.yaml"] = "- scalar\n"

    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files)

    assert any("yaml root must be an object" in error.lower() for error in exc_info.value.errors)


def test_validator_rejects_manifest_identity_changed_by_agent():
    files = _base_files(tool_py="pass\n")
    files["manifest.yaml"] = "author: agent\nname: invented_name\n"

    with pytest.raises(ToolPluginValidationError) as exc_info:
        validate_plugin_files(files, author="ghy", plugin_name="user_plugin")

    assert any("session identity" in error.lower() for error in exc_info.value.errors)
