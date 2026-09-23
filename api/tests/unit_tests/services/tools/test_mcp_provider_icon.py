from unittest.mock import Mock, patch

from core.entities.mcp_provider import MCPConfiguration
from services.tools.mcp_tools_manage_service import MCPToolManageService, ReconnectResult


def test_create_provider_falls_back_when_remote_icon_exceeds_database_limit() -> None:
    session = Mock()
    service = MCPToolManageService(session)
    connection = ReconnectResult(
        authed=True,
        tools='[{"name":"search"}]',
        encrypted_credentials="{}",
        server_icon="data:image/png;base64," + "A" * 400,
    )

    with (
        patch.object(service, "_check_provider_exists"),
        patch("services.tools.mcp_tools_manage_service.encrypter.encrypt_token", return_value="encrypted-url"),
        patch("services.tools.mcp_tools_manage_service.ToolTransformService.mcp_provider_to_user_provider"),
    ):
        service.create_provider(
            tenant_id="b36be510-8e66-4c1d-ae55-82760f3a2c87",
            name="GitHub Copilot",
            server_url="https://api.githubcopilot.com/mcp",
            user_id="5f558ebc-4b62-431c-8505-eaf7087980d3",
            icon="MCP",
            icon_type="emoji",
            icon_background="#eef2ff",
            server_identifier="githubcopilot",
            configuration=MCPConfiguration(timeout=60, sse_read_timeout=300),
            connection_result=connection,
        )

    provider = session.add.call_args.args[0]
    assert provider.icon == '{"content": "MCP", "background": "#eef2ff"}'
    assert len(provider.icon) <= 255
    assert provider.authed is True
    assert provider.tools == '[{"name":"search"}]'
