"""One-shot authorization for live tool-plugin verification.

Issuing an authorization never installs or invokes a plugin. It stores only a
short-lived payload digest in Redis; consumption is required by the publish
endpoint immediately before the operation that can call external APIs.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from extensions.ext_redis import redis_client
from services.tool_plugin_generator.preview_mapper import map_files_to_preview_tool
from services.tool_plugin_generator.session_service import get_session
from services.tool_plugin_generator.validator import ToolPluginValidationError

AUTHORIZATION_TTL_SECONDS = 300


class TestAuthorizationError(ValueError):
    """Raised when a live-test authorization is missing, stale, or mismatched."""


def _digest_payload(
    *,
    session_id: str,
    revision: int,
    tool_name: str,
    parameters: dict[str, Any],
    credentials: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "session_id": session_id,
            "revision": revision,
            "tool_name": tool_name,
            "parameters": parameters,
            "credentials": credentials,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authorization_key(*, tenant_id: str, account_id: str, session_id: str, token: str) -> str:
    return f"tool_plugin_test_authorization:{tenant_id}:{account_id}:{session_id}:{token}"


def issue_test_authorization(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    expected_revision: int,
    tool_name: str,
    parameters: dict[str, Any],
    credentials: dict[str, Any],
) -> dict[str, Any]:
    """Issue a five-minute one-shot token bound to the exact test payload."""
    session = get_session(tenant_id=tenant_id, account_id=account_id, session_id=session_id)
    if session.revision != expected_revision:
        raise TestAuthorizationError(
            f"Session revision conflict: expected {expected_revision}, current {session.revision}"
        )
    if session.active_tool_name != tool_name:
        raise TestAuthorizationError("tool_name must match the session's active tool")
    try:
        preview = map_files_to_preview_tool(
            session.files,
            author=session.author,
            plugin_name=session.plugin_name,
            tool_name=tool_name,
        )
    except (ToolPluginValidationError, ValueError) as exc:
        message = "; ".join(exc.errors) if isinstance(exc, ToolPluginValidationError) else str(exc)
        raise TestAuthorizationError(f"Draft is not ready for live testing: {message}") from exc
    token = secrets.token_urlsafe(32)
    metadata = {
        "digest": _digest_payload(
            session_id=session_id,
            revision=expected_revision,
            tool_name=tool_name,
            parameters=parameters,
            credentials=credentials,
        ),
        "tool_name": tool_name,
        "revision": expected_revision,
    }
    key = _authorization_key(tenant_id=tenant_id, account_id=account_id, session_id=session_id, token=token)
    if not redis_client.set(
        key,
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
        ex=AUTHORIZATION_TTL_SECONDS,
        nx=True,
    ):
        raise TestAuthorizationError("Could not reserve a live-test authorization; please retry")
    return {
        "token": token,
        "expires_in": AUTHORIZATION_TTL_SECONDS,
        "max_calls": 1,
        "tool_name": tool_name,
        "provider_id": str(preview.get("provider_id") or ""),
        "parameter_count": len(parameters),
        "credential_names": sorted(str(name) for name in credentials),
    }


def consume_test_authorization(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    expected_revision: int,
    tool_name: str,
    parameters: dict[str, Any],
    credentials: dict[str, Any],
    token: str,
) -> None:
    """Atomically consume and verify a token immediately before live testing."""
    key = _authorization_key(tenant_id=tenant_id, account_id=account_id, session_id=session_id, token=token)
    raw = redis_client.getdel(key)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not raw:
        raise TestAuthorizationError("Live-test authorization is missing, expired, or already used")
    try:
        metadata = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TestAuthorizationError("Live-test authorization is invalid") from exc
    expected_digest = _digest_payload(
        session_id=session_id,
        revision=expected_revision,
        tool_name=tool_name,
        parameters=parameters,
        credentials=credentials,
    )
    if (
        not isinstance(metadata, dict)
        or metadata.get("digest") != expected_digest
        or metadata.get("revision") != expected_revision
        or metadata.get("tool_name") != tool_name
    ):
        raise TestAuthorizationError("Live-test authorization does not match the current draft or parameters")
