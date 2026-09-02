from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from core.mcp.types import Icon

_BLOCKED_HOST_SUFFIXES = (".internal", ".local", ".localhost")
_DANGEROUS_PORTS = frozenset({21, 22, 23, 25, 110, 143, 2375, 2376, 3306, 5432, 6379, 9200, 11211, 27017})
_PROXY_FAKE_IPV4_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_SAFE_ICON_DATA_URI = re.compile(r"^data:image/(?:png|jpeg|webp);base64,[a-z0-9+/=\s]+$", re.IGNORECASE)


def validate_remote_mcp_url(server_url: str) -> str:
    """Validate and normalize a remote MCP URL without performing DNS I/O."""
    normalized_url = server_url.strip()
    parsed = urlparse(normalized_url)
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Remote MCP Server URL contains an invalid port.") from exc

    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise ValueError("Remote MCP Server URL must use HTTPS and must not contain credentials.")

    normalized_hostname = hostname.rstrip(".").casefold()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise ValueError("Remote MCP Server URL must target a public network host.")
    if port in _DANGEROUS_PORTS:
        raise ValueError("Remote MCP Server URL uses a blocked infrastructure port.")

    try:
        address = ipaddress.ip_address(normalized_hostname)
    except ValueError:
        pass
    else:
        _require_public_address(address)

    return normalized_url


def validate_remote_mcp_network_target(server_url: str) -> str:
    """Resolve a remote MCP host and reject unsafe destinations.

    Domain names may resolve to the benchmarking range used by proxy Fake-IP DNS. Direct URLs targeting that
    range remain blocked by :func:`validate_remote_mcp_url`, so the exception cannot be used to bypass hostname
    validation.
    """
    normalized_url = validate_remote_mcp_url(server_url)
    parsed = urlparse(normalized_url)
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("Remote MCP Server URL must include a hostname.")

    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Remote MCP Server hostname could not be resolved.") from exc
    if not addresses:
        raise ValueError("Remote MCP Server hostname could not be resolved.")

    for address_info in addresses:
        address = ipaddress.ip_address(address_info[4][0])
        if isinstance(address, ipaddress.IPv4Address) and address in _PROXY_FAKE_IPV4_NETWORK:
            continue
        _require_public_address(address)
    return normalized_url


def validate_mcp_redirect(response: httpx.Response) -> None:
    """Revalidate every HTTP redirect before the MCP client follows it."""
    if not response.is_redirect:
        return
    location = response.headers.get("location")
    if location:
        validate_remote_mcp_network_target(urljoin(str(response.request.url), location))


def select_safe_mcp_icon(server_url: str, icons: list[Icon] | None) -> str | None:
    """Select an icon that can be rendered without contacting an unrelated origin."""
    if not icons:
        return None

    server = urlparse(server_url)
    server_origin = _https_origin(server)
    for icon in icons:
        source = icon.src.strip()
        if _SAFE_ICON_DATA_URI.fullmatch(source):
            return source

        parsed_icon = urlparse(source)
        if server_origin is not None and _https_origin(parsed_icon) == server_origin:
            return source
    return None


def _https_origin(parsed_url) -> tuple[str, int] | None:
    if parsed_url.scheme.casefold() != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        return None
    try:
        port = parsed_url.port or 443
    except ValueError:
        return None
    return parsed_url.hostname.rstrip(".").casefold(), port


def _require_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if not address.is_global:
        raise ValueError("Remote MCP Server URL must target a public network host.")
