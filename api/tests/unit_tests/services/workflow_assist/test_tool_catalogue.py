from types import SimpleNamespace
from unittest.mock import patch

from core.tools.builtin_tool.provider import BuiltinToolProviderController
from core.tools.plugin_tool.provider import PluginToolProviderController
from core.workflow.generator.resources.knowledge_catalogue import _MAX_DATASETS
from core.workflow.generator.resources.tool_catalogue import _MAX_TOOLS
from services.workflow_assist.knowledge_catalogue import list_assist_knowledge_catalogue
from services.workflow_assist.tool_catalogue import list_assist_tool_catalogue
from services.workflow_assist.tool_catalogue_loader import build_tool_catalogue


class _HardcodedProvider(BuiltinToolProviderController):
    def _validate_credentials(self, user_id: str, credentials: dict) -> None:
        pass


def _entry(index: int) -> dict:
    return {
        "provider_name": f"provider-{index // 10}",
        "provider_type": "builtin",
        "plugin_id": "",
        "tool_name": f"tool-{index}",
        "tool_label": f"Tool {index}",
        "description": f"desc {index}",
    }


def _provider(controller_type, provider_name: str, tool_name: str):
    provider = object.__new__(controller_type)
    provider.entity = SimpleNamespace(identity=SimpleNamespace(name=provider_name))
    provider.get_tools = lambda: [
        SimpleNamespace(
            entity=SimpleNamespace(
                identity=SimpleNamespace(
                    name=tool_name,
                    label=SimpleNamespace(en_US=tool_name, zh_Hans=""),
                ),
                description=SimpleNamespace(llm="description", human=None),
                parameters=[],
                output_schema={},
            )
        )
    ]
    if isinstance(provider, PluginToolProviderController):
        provider.plugin_id = "acme/time"
        provider.plugin_unique_identifier = "acme/time:1.0.0"
    return provider


def test_build_tool_catalogue_excludes_only_hardcoded_name_collision(monkeypatch) -> None:
    hardcoded = _provider(_HardcodedProvider, "time", "current_time")
    plugin = _provider(PluginToolProviderController, "time", "custom_time")
    monkeypatch.setattr(
        "services.workflow_assist.tool_catalogue_loader.ToolManager.list_builtin_providers",
        lambda _tenant_id: [hardcoded, plugin],
    )
    monkeypatch.setattr(
        "services.workflow_assist.tool_catalogue_loader._installed_plugin_index",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "services.workflow_assist.tool_catalogue_loader._mcp_catalogue_entries",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "core.tools.tool_manager.dify_config",
        SimpleNamespace(POSITION_TOOL_INCLUDES_SET=set(), POSITION_TOOL_EXCLUDES_SET={"time"}),
    )

    catalogue = build_tool_catalogue("tenant-1", limit=None)

    assert [(entry["plugin_id"], entry["tool_name"]) for entry in catalogue] == [
        ("acme/time", "custom_time")
    ]


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
