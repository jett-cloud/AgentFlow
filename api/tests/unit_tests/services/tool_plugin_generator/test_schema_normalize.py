import pytest
import yaml

from services.tool_plugin_generator.packager import normalize_plugin_source_files
from services.tool_plugin_generator.schema_normalize import (
    as_i18n,
    normalize_provider_yaml_content,
    normalize_tool_parameter,
    normalize_tool_parameters,
    normalize_tool_yaml_content,
    repair_yaml_unquoted_colon_scalars,
)


def test_normalize_tool_parameter_adds_form_and_i18n_label():
    normalized = normalize_tool_parameter(
        {
            "name": "parent_id",
            "type": "string",
            "required": True,
            "label": "Parent ID",
            "description": "Parent page id to create the new page.",
        }
    )

    assert normalized["form"] == "llm"
    assert normalized["label"] == {"en_US": "Parent ID"}
    assert normalized["human_description"]["en_US"]
    assert normalized["llm_description"]


def test_normalize_tool_yaml_content_rewrites_parameters():
    content = """
identity:
  name: create_page
  author: acme
  label:
    en_US: Create Page
parameters:
  - name: parent_id
    type: string
    required: true
    label: Parent ID
extra:
  python:
    source: tools/create_page.py
"""
    rewritten = normalize_tool_yaml_content(content)
    assert "form: llm" in rewritten
    assert "en_US: Parent ID" in rewritten
    assert "label: Parent ID" not in rewritten


def test_normalize_tool_parameters_rejects_missing_name():
    with pytest.raises(ValueError, match="non-empty name"):
        normalize_tool_parameters([{"type": "string"}])


def test_as_i18n_fills_en_us_from_zh_hans():
    assert as_i18n({"zh_Hans": "火山方舟"}, fallback="Ark") == {
        "zh_Hans": "火山方舟",
        "en_US": "火山方舟",
    }


def test_normalize_tool_yaml_fills_identity_en_us_from_zh_hans():
    content = """
identity:
  name: image_tool
  author: ghy
  label:
    zh_Hans: 视频生成任务
  icon: icon.svg
description:
  human:
    zh_Hans: 创建视频生成任务
  llm: create video task
parameters: []
"""
    loaded = yaml.safe_load(normalize_tool_yaml_content(content))
    assert loaded["identity"]["label"]["en_US"] == "视频生成任务"
    assert loaded["description"]["human"]["en_US"] == "创建视频生成任务"


def test_normalize_provider_yaml_fills_credential_and_identity_en_us():
    content = """
identity:
  author: ghy
  name: doubao_tool
  label:
    zh_Hans: 火山方舟
  description:
    zh_Hans: 火山引擎方舟平台视频生成
  icon: icon.svg
credentials_for_provider:
  api_key:
    type: secret-input
    required: true
    label:
      zh_Hans: API Key
"""
    loaded = yaml.safe_load(normalize_provider_yaml_content(content))
    assert loaded["identity"]["label"]["en_US"] == "火山方舟"
    assert loaded["identity"]["description"]["en_US"] == "火山引擎方舟平台视频生成"
    assert loaded["credentials_for_provider"]["api_key"]["label"]["en_US"] == "API Key"


def test_normalize_plugin_source_files_covers_provider_and_tool():
    files = {
        "manifest.yaml": "name: doubao_tool\nlabel:\n  zh_Hans: 方舟\ndescription:\n  zh_Hans: desc\n",
        "provider/doubao_tool.yaml": (
            "identity:\n  name: doubao_tool\n  label:\n    zh_Hans: 火山方舟\n"
            "credentials_for_provider:\n  api_key:\n    type: secret-input\n"
            "    label:\n      zh_Hans: API Key\n"
        ),
        "provider/doubao_tool.py": "pass\n",
        "tools/image_tool.yaml": (
            "identity:\n  name: image_tool\n  label:\n    zh_Hans: 视频生成任务\n"
            "description:\n  human:\n    zh_Hans: 创建任务\n  llm: create\nparameters: []\n"
        ),
        "tools/image_tool.py": "pass\n",
    }
    normalized = normalize_plugin_source_files(files)
    assert yaml.safe_load(normalized["manifest.yaml"])["label"]["en_US"] == "方舟"
    provider = yaml.safe_load(normalized["provider/doubao_tool.yaml"])
    assert provider["identity"]["label"]["en_US"]
    assert provider["tools"] == ["tools/image_tool.yaml"]
    assert provider["extra"]["python"]["source"] == "provider/doubao_tool.py"
    tool = yaml.safe_load(normalized["tools/image_tool.yaml"])
    assert tool["identity"]["label"]["en_US"]
    assert tool["extra"]["python"]["source"] == "tools/image_tool.py"


def test_normalize_repairs_unquoted_colon_in_description():
    broken = """
identity:
  name: generate_image
parameters:
  - name: style
    type: string
    required: false
    label:
      en_US: Style
    human_description:
      en_US: Optional image style. Supported values: realistic, anime, 3d, watercolor.
    llm_description: Optional image style. Supported values: realistic, anime, 3d, watercolor.
    form: llm
"""
    repaired = repair_yaml_unquoted_colon_scalars(broken)
    assert yaml.safe_load(repaired) is not None
    rewritten = normalize_tool_yaml_content(broken)
    loaded = yaml.safe_load(rewritten)
    assert isinstance(loaded, dict)
    assert loaded["parameters"][0]["form"] == "llm"
    assert "Supported values:" in loaded["parameters"][0]["human_description"]["en_US"]
