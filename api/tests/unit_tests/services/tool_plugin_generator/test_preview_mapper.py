from services.tool_plugin_generator.preview_mapper import (
    map_files_to_preview_tool,
    normalize_plugin_provider_id,
)


def test_preview_mapper_reads_parameters_from_tool_yaml():
    files = {
        "tools/echo.yaml": """
identity:
  name: echo
parameters:
  - name: text
    type: string
    required: true
""",
        "provider/demo.yaml": "identity:\n  name: demo\n",
    }
    preview = map_files_to_preview_tool(files, author="acme", plugin_name="demo")
    assert preview["tool_name"] == "echo"
    assert preview["provider_type"] in ("builtin", "plugin")
    assert preview["provider_id"] == "acme/demo/demo"
    assert preview["provider_name"] == "demo"
    assert preview["parameters_schema"][0]["name"] == "text"
    assert isinstance(preview["tool_parameters"], dict)
    assert preview["credentials_schema"] == []


def test_normalize_plugin_provider_id_upgrades_two_segment_ids():
    assert normalize_plugin_provider_id("ghy/doubao_image_tools") == (
        "ghy/doubao_image_tools/doubao_image_tools"
    )
    assert (
        normalize_plugin_provider_id("ghy/doubao_image_tools/doubao_image_tools")
        == "ghy/doubao_image_tools/doubao_image_tools"
    )


def test_normalize_plugin_provider_id_sanitizes_dotted_segments():
    assert normalize_plugin_provider_id("ghy/remove.bg", provider_name="remove-bg") == (
        "ghy/remove-bg/remove-bg"
    )
    assert normalize_plugin_provider_id("ghy/remove.bg/remove-bg") == "ghy/remove-bg/remove-bg"


def test_preview_mapper_extracts_credentials_schema_from_provider_yaml():
    files = {
        "tools/generate_image.yaml": """
identity:
  name: generate_image
parameters:
  - name: prompt
    type: string
    required: true
""",
        "provider/image.yaml": """
identity:
  name: image
credentials_for_provider:
  api_key:
    type: secret-input
    required: true
    label:
      en_US: API Key
      zh_Hans: API 密钥
""",
    }
    preview = map_files_to_preview_tool(files, author="acme", plugin_name="image")
    assert preview["provider_id"] == "acme/image/image"
    assert len(preview["credentials_schema"]) == 1
    assert preview["credentials_schema"][0]["name"] == "api_key"
    assert preview["credentials_schema"][0]["type"] == "secret-input"
