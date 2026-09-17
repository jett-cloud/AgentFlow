from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core.plugin.impl.plugin import PluginInstaller
from core.plugin.plugin_service import PluginService
from services.tool_plugin_generator.service import (
    plugin_id_from_unique_identifier,
    uninstall_installations_for_plugin_id,
)
from services.tool_plugin_generator.session_service import (
    ToolPluginStudioSessionError,
    acquire_plugin_publish_lock,
    acquire_session_operation_lock,
    delete_sessions_by_installation,
    list_sessions,
    list_sessions_by_installation,
    release_session_operation_lock,
)

logger = logging.getLogger(__name__)


@dataclass
class UninstallWithSessionsResult:
    success: bool
    deleted_session_ids: list[str] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PurgeByPluginIdResult:
    plugin_id: str
    uninstalled_installation_ids: list[str] = field(default_factory=list)
    failed_installation_ids: list[str] = field(default_factory=list)
    deleted_session_ids: list[str] = field(default_factory=list)


def _session_ids(sessions: list[dict[str, Any]]) -> list[str]:
    return sorted({str(item["id"]) for item in sessions if item.get("id")})


def _resolve_installed_plugin_id(
    *,
    tenant_id: str,
    installation_id: str,
    plugin_unique_identifier: str | None,
    sessions: list[dict[str, Any]],
) -> str:
    try:
        installed = PluginInstaller().list_plugins(tenant_id)
    except Exception as exc:
        raise ToolPluginStudioSessionError("Unable to verify plugin identity before uninstall") from exc
    matched = next(
        (plugin for plugin in installed if str(getattr(plugin, "installation_id", "")) == installation_id),
        None,
    )
    if matched is not None and getattr(matched, "plugin_id", None):
        return str(matched.plugin_id)
    identifiers = [plugin_unique_identifier]
    identifiers.extend(str(item.get("plugin_unique_identifier") or "") for item in sessions)
    for identifier in identifiers:
        plugin_id = plugin_id_from_unique_identifier(str(identifier or ""))
        if plugin_id:
            return plugin_id
    raise ToolPluginStudioSessionError("Unable to resolve plugin identity before uninstall")


def _sessions_for_plugin_id(*, tenant_id: str, account_id: str, plugin_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in list_sessions(tenant_id=tenant_id, account_id=account_id, include_hidden=True)
        if item.get("installation_id")
        and plugin_id_from_unique_identifier(str(item.get("plugin_unique_identifier") or "")) == plugin_id
    ]


def _acquire_mutation_locks(
    *,
    tenant_id: str,
    account_id: str,
    plugin_id: str,
    session_ids: list[str],
) -> list[Any]:
    locks: list[Any] = []
    try:
        for session_id in sorted(set(session_ids)):
            locks.append(
                acquire_session_operation_lock(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    session_id=session_id,
                )
            )
        locks.append(acquire_plugin_publish_lock(tenant_id=tenant_id, plugin_id=plugin_id))
    except Exception:
        for lock in reversed(locks):
            release_session_operation_lock(lock)
        raise
    return locks


def _release_mutation_locks(locks: list[Any]) -> None:
    for lock in reversed(locks):
        release_session_operation_lock(lock)


def preview_sessions_for_installation(
    *,
    tenant_id: str,
    account_id: str,
    plugin_installation_id: str,
    plugin_unique_identifier: str | None = None,
) -> list[dict[str, Any]]:
    return list_sessions_by_installation(
        tenant_id=tenant_id,
        account_id=account_id,
        installation_id=plugin_installation_id,
        plugin_unique_identifier=plugin_unique_identifier,
    )


def uninstall_plugin_with_studio_sessions(
    *,
    tenant_id: str,
    account_id: str,
    plugin_installation_id: str,
    delete_studio_sessions: bool = True,
    plugin_unique_identifier: str | None = None,
) -> UninstallWithSessionsResult:
    """Uninstall a plugin and optionally delete linked AI studio sessions."""
    sessions = preview_sessions_for_installation(
        tenant_id=tenant_id,
        account_id=account_id,
        plugin_installation_id=plugin_installation_id,
        plugin_unique_identifier=plugin_unique_identifier,
    )
    plugin_id = _resolve_installed_plugin_id(
        tenant_id=tenant_id,
        installation_id=plugin_installation_id,
        plugin_unique_identifier=plugin_unique_identifier,
        sessions=sessions,
    )
    locked_session_ids = _session_ids(sessions)
    locks = _acquire_mutation_locks(
        tenant_id=tenant_id,
        account_id=account_id,
        plugin_id=plugin_id,
        session_ids=locked_session_ids,
    )
    try:
        sessions = preview_sessions_for_installation(
            tenant_id=tenant_id,
            account_id=account_id,
            plugin_installation_id=plugin_installation_id,
            plugin_unique_identifier=plugin_unique_identifier,
        )
        if set(_session_ids(sessions)) - set(locked_session_ids):
            raise ToolPluginStudioSessionError("Linked studio sessions changed; retry uninstall", code="conflict")
        success = PluginService.uninstall(tenant_id, plugin_installation_id)
        deleted_session_ids: list[str] = []
        if success and delete_studio_sessions:
            try:
                deleted_session_ids = delete_sessions_by_installation(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    installation_id=plugin_installation_id,
                    plugin_unique_identifier=plugin_unique_identifier,
                )
            except Exception:
                logger.warning(
                    "Plugin uninstalled but studio session cleanup failed installation_id=%s",
                    plugin_installation_id,
                    exc_info=True,
                )
    finally:
        _release_mutation_locks(locks)
    return UninstallWithSessionsResult(
        success=bool(success),
        deleted_session_ids=deleted_session_ids,
        sessions=sessions,
    )


def purge_installations_for_plugin_id(
    *,
    tenant_id: str,
    account_id: str,
    plugin_id: str,
    delete_studio_sessions: bool = True,
) -> PurgeByPluginIdResult:
    """Uninstall all installations for plugin_id and optionally clear studio sessions."""
    sessions = _sessions_for_plugin_id(tenant_id=tenant_id, account_id=account_id, plugin_id=plugin_id)
    locked_session_ids = _session_ids(sessions)
    locks = _acquire_mutation_locks(
        tenant_id=tenant_id,
        account_id=account_id,
        plugin_id=plugin_id,
        session_ids=locked_session_ids,
    )
    try:
        sessions = _sessions_for_plugin_id(tenant_id=tenant_id, account_id=account_id, plugin_id=plugin_id)
        if set(_session_ids(sessions)) - set(locked_session_ids):
            raise ToolPluginStudioSessionError("Linked studio sessions changed; retry purge", code="conflict")
        uninstall_result = uninstall_installations_for_plugin_id(tenant_id=tenant_id, plugin_id=plugin_id)
        deleted_session_ids: list[str] = []
        if delete_studio_sessions:
            for installation_id in uninstall_result.uninstalled_installation_ids:
                try:
                    deleted_session_ids.extend(
                        delete_sessions_by_installation(
                            tenant_id=tenant_id,
                            account_id=account_id,
                            installation_id=installation_id,
                        )
                    )
                except Exception:
                    logger.warning(
                        "Purged plugin installation but studio session cleanup failed installation_id=%s",
                        installation_id,
                        exc_info=True,
                    )
    finally:
        _release_mutation_locks(locks)
    return PurgeByPluginIdResult(
        plugin_id=uninstall_result.plugin_id,
        uninstalled_installation_ids=uninstall_result.uninstalled_installation_ids,
        failed_installation_ids=uninstall_result.failed_installation_ids,
        deleted_session_ids=deleted_session_ids,
    )
