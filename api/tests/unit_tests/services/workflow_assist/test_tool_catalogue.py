from unittest.mock import patch

from core.workflow.generator.knowledge_catalogue import _MAX_DATASETS
from core.workflow.generator.tool_catalogue import _MAX_TOOLS
from services.workflow_assist.knowledge_catalogue import list_assist_knowledge_catalogue
from services.workflow_assist.tool_catalogue import list_assist_tool_catalogue


def _entry(index: int) -> dict:
    return {
        "provider_name": f"provider-{index // 10}",
        "provider_type": "builtin",
        "plugin_id": "",
        "tool_name": f"tool-{index}",
        "tool_label": f"Tool {index}",
        "description": f"desc {index}",
    }


@patch("services.workflow_assist.tool_catalogue.build_tool_catalogue")
def test_list_assist_tool_catalogue_empty(build_tool_catalogue):
    build_tool_catalogue.return_value = []

    result = list_assist_tool_catalogue("tenant-1")

    build_tool_catalogue.assert_called_once_with("tenant-1", limit=None)
    assert result["tools"] == []
    assert result["truncated"] is False
    assert result["max_tools"] == _MAX_TOOLS
    assert result["total_before_cap"] == 0


@patch("services.workflow_assist.tool_catalogue.build_tool_catalogue")
def test_list_assist_tool_catalogue_truncates_above_max(build_tool_catalogue):
    build_tool_catalogue.return_value = [_entry(i) for i in range(_MAX_TOOLS + 1)]

    result = list_assist_tool_catalogue("tenant-1")

    assert result["truncated"] is True
    assert result["max_tools"] == _MAX_TOOLS
    assert result["total_before_cap"] == _MAX_TOOLS + 1
    assert len(result["tools"]) == _MAX_TOOLS
    assert result["tools"][0]["tool_name"] == "tool-0"
    assert result["tools"][-1]["tool_name"] == f"tool-{_MAX_TOOLS - 1}"


@patch("services.workflow_assist.tool_catalogue.build_tool_catalogue")
def test_list_assist_tool_catalogue_exact_max_not_truncated(build_tool_catalogue):
    build_tool_catalogue.return_value = [_entry(i) for i in range(_MAX_TOOLS)]

    result = list_assist_tool_catalogue("tenant-1")

    assert result["truncated"] is False
    assert len(result["tools"]) == _MAX_TOOLS
    assert result["total_before_cap"] == _MAX_TOOLS


@patch("services.workflow_assist.knowledge_catalogue.build_knowledge_catalogue")
def test_list_assist_knowledge_catalogue_truncates_above_max(build_knowledge_catalogue):
    build_knowledge_catalogue.return_value = [
        {"id": f"dataset-{index}", "name": f"Dataset {index}", "description": ""} for index in range(_MAX_DATASETS + 1)
    ]

    result = list_assist_knowledge_catalogue("tenant-1")

    build_knowledge_catalogue.assert_called_once_with("tenant-1", limit=None)
    assert result["truncated"] is True
    assert result["max_datasets"] == _MAX_DATASETS
    assert result["total_before_cap"] == _MAX_DATASETS + 1
    assert len(result["datasets"]) == _MAX_DATASETS
