from __future__ import annotations

from controllers.console.workspace import tool_providers


def test_remote_mcp_controller_has_no_ai_configuration_surface() -> None:
    assert not hasattr(tool_providers, "MCPRemoteAIConfigureApi")
    assert not hasattr(tool_providers, "MCPRemoteAIConfigurePayload")
