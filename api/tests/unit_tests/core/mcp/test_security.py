from __future__ import annotations

import socket
from unittest.mock import patch

import httpx
import pytest

from core.mcp.security import (
    select_safe_mcp_icon,
    validate_mcp_redirect,
    validate_remote_mcp_network_target,
    validate_remote_mcp_url,
)
from core.mcp.types import Icon


def test_validate_remote_mcp_url_rejects_local_and_dangerous_targets() -> None:
    for url in (
        "https://localhost/mcp",
        "https://127.0.0.1/mcp",
        "https://10.0.0.8/mcp",
        "https://198.18.0.105/mcp",
        "https://example.com:6379/mcp",
    ):
        with pytest.raises(ValueError):
            validate_remote_mcp_url(url)


def test_validate_remote_mcp_network_target_rejects_private_dns_result() -> None:
    private_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))]
    with patch("core.mcp.security.socket.getaddrinfo", return_value=private_result):
        with pytest.raises(ValueError, match="public network"):
            validate_remote_mcp_network_target("https://mcp.example.com/mcp")


def test_validate_remote_mcp_network_target_allows_proxy_fake_ip_for_hostname() -> None:
    fake_ip_result = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.105", 443))]
    with patch("core.mcp.security.socket.getaddrinfo", return_value=fake_ip_result):
        assert validate_remote_mcp_network_target("https://api.githubcopilot.com/mcp") == (
            "https://api.githubcopilot.com/mcp"
        )


def test_validate_mcp_redirect_rechecks_redirect_target() -> None:
    request = httpx.Request("GET", "https://mcp.example.com/mcp")
    response = httpx.Response(302, headers={"location": "https://127.0.0.1/admin"}, request=request)

    with pytest.raises(ValueError):
        validate_mcp_redirect(response)


def test_select_safe_mcp_icon_accepts_same_origin_https_icon() -> None:
    icons = [Icon(src="https://mcp.example.com/assets/icon.png", mimeType="image/png")]

    assert select_safe_mcp_icon("https://mcp.example.com/mcp", icons) == icons[0].src


def test_select_safe_mcp_icon_uses_first_safe_candidate() -> None:
    icons = [
        Icon(src="https://cdn.example.com/icon.png", mimeType="image/png"),
        Icon(src="data:image/webp;base64,UklGRg==", mimeType="image/webp"),
    ]

    assert select_safe_mcp_icon("https://mcp.example.com/mcp", icons) == icons[1].src


@pytest.mark.parametrize(
    "icon_src",
    [
        "http://mcp.example.com/icon.png",
        "https://cdn.example.com/icon.png",
        "data:image/svg+xml,<svg onload=alert(1) />",
        "javascript:alert(1)",
    ],
)
def test_select_safe_mcp_icon_rejects_untrusted_icon_sources(icon_src: str) -> None:
    assert (
        select_safe_mcp_icon(
            "https://mcp.example.com/mcp",
            [Icon(src=icon_src)],
        )
        is None
    )
