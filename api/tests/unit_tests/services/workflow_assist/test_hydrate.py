from copy import deepcopy
from unittest.mock import MagicMock, patch

from services.workflow_assist.hydrate import hydrate_agent_bindings


def _graph(nodes: list[dict]) -> dict:
    return {"nodes": nodes, "edges": []}


@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_fills_missing_inline_ids(create_inline_binding_for_node: MagicMock):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                },
            }
        ]
    )
    original_graph = deepcopy(graph)

    result = hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    assert result["nodes"][0]["data"] == {
        "type": "agent",
        "version": "2",
        "agent_binding": {
            "binding_type": "inline_agent",
            "agent_id": "aid",
            "current_snapshot_id": "sid",
        },
        "agent_node_kind": "dify_agent",
    }
    assert graph == original_graph
    create_inline_binding_for_node.assert_called_once_with(
        session=create_inline_binding_for_node.call_args.kwargs["session"],
        tenant_id="tenant",
        app_id="app",
        workflow_id="workflow",
        node_id="agent-node",
        account_id="account",
        agent_soul=None,
    )


@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_copies_generated_model_into_agent_soul(create_inline_binding_for_node: MagicMock):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                    "model": {
                        "provider": "langgenius/openai/openai",
                        "name": "gpt-4o",
                        "mode": "chat",
                        "completion_params": {"temperature": 0.3, "top_p": 0.8},
                    },
                },
            }
        ]
    )

    hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    soul = create_inline_binding_for_node.call_args.kwargs.get("agent_soul")
    assert soul is not None
    assert soul.model is not None
    assert soul.model.plugin_id == "langgenius/openai"
    assert soul.model.model_provider == "langgenius/openai/openai"
    assert soul.model.model == "gpt-4o"
    assert soul.model.model_settings.temperature == 0.3
    assert soul.model.model_settings.top_p == 0.8


@patch("services.workflow_assist.hydrate.create_inline_binding_for_node", return_value=("aid", "sid"))
def test_hydrate_copies_generated_dify_tools_into_agent_soul(create_inline_binding_for_node: MagicMock):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": 2,
                    "model": {
                        "provider": "langgenius/openai/openai",
                        "name": "gpt-4o",
                    },
                    "dify_tools": [
                        {
                            "provider_type": "mcp",
                            "provider_id": "github-official",
                            "tool_name": None,
                            "credential_type": "unauthorized",
                        }
                    ],
                },
            }
        ]
    )

    hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    soul = create_inline_binding_for_node.call_args.kwargs.get("agent_soul")
    assert soul is not None
    assert len(soul.tools.dify_tools) == 1
    assert soul.tools.dify_tools[0].provider_type == "mcp"
    assert soul.tools.dify_tools[0].provider_id == "github-official"
    assert soul.tools.dify_tools[0].tool_name is None


@patch("services.workflow_assist.hydrate.create_inline_binding_for_node")
def test_hydrate_skips_already_bound(create_inline_binding_for_node: MagicMock):
    graph = _graph(
        [
            {
                "id": "agent-node",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_binding": {
                        "binding_type": "inline_agent",
                        "agent_id": "aid",
                        "current_snapshot_id": "sid",
                    },
                },
            }
        ]
    )

    result = hydrate_agent_bindings(
        session=MagicMock(),
        tenant_id="tenant",
        app_id="app",
        account_id="account",
        workflow_id="workflow",
        graph=graph,
    )

    assert result == graph
    create_inline_binding_for_node.assert_not_called()
