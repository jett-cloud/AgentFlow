"""Tenant plugin and MCP inventory loading."""

import logging
from dataclasses import dataclass
from operator import itemgetter

from core.tools.builtin_tool.provider import BuiltinToolProviderController
from core.tools.plugin_tool.provider import PluginToolProviderController
from core.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)

from core.workflow.generator.resources.tool_catalogue import (
    _MAX_TOOLS,
    ToolCatalogueEntry,
    _i18n_text,
    _tool_description,
    _with_schema,
    _with_search_aliases,
)


@dataclass(frozen=True)
class _InstalledPluginIndex:
    """Live plugin installations for one tenant.

    ``None`` from ``_installed_plugin_index`` means the lookup failed and
    callers must not filter. An empty index means the tenant has no plugins,
    so daemon leftovers after uninstall must be dropped.
    """

    plugin_ids: frozenset[str]
    unique_identifiers: frozenset[str]


def _installed_plugin_index(tenant_id: str, *, raise_on_error: bool = False) -> _InstalledPluginIndex | None:
    """Return live installations, or ``None`` when the lookup cannot run.

    ``None`` disables filtering so a daemon outage does not empty the plugin
    catalogue. An empty index is a successful "this tenant has no plugins".
    """
    try:
        from core.plugin.impl.plugin import PluginInstaller

        plugins = PluginInstaller().list_plugins(tenant_id)
    except Exception:
        logger.exception("Workflow generator: failed to list installed plugins")
        if raise_on_error:
            raise
        return None
    return _InstalledPluginIndex(
        plugin_ids=frozenset(str(plugin.plugin_id) for plugin in plugins if plugin.plugin_id),
        unique_identifiers=frozenset(
            str(plugin.plugin_unique_identifier) for plugin in plugins if plugin.plugin_unique_identifier
        ),
    )


def _plugin_still_installed(provider: object, installed: _InstalledPluginIndex | None) -> bool:
    """True when ``provider`` is still in the tenant install list.

    Prefer ``plugin_unique_identifier`` so a republish that leaves the same
    ``plugin_id`` still drops the uninstalled package the daemon may list.
    """
    if installed is None:
        return True
    unique = str(getattr(provider, "plugin_unique_identifier", "") or "")
    if unique:
        return unique in installed.unique_identifiers
    plugin_id = str(getattr(provider, "plugin_id", "") or "")
    return bool(plugin_id) and plugin_id in installed.plugin_ids


def build_tool_catalogue(
    tenant_id: str,
    *,
    limit: int | None = _MAX_TOOLS,
    raise_on_error: bool = False,
) -> list[ToolCatalogueEntry]:
    """
    Enumerate installed tools for the given tenant.

    Failures inside a single provider (mis-declared tool, plugin runtime
    error) are logged and skipped — one bad provider must not break the
    whole generator. When ``limit`` is an int, returns at most that many
    entries (default ``_MAX_TOOLS``). Pass ``limit=None`` for the uncapped
    list (used for Workflow Assist's complete authorization snapshot).

    Plugin providers come from the daemon tool index, which can briefly keep
    a just-uninstalled package. Cross-check against ``management/list`` so
    Assist ``search_tools`` cannot bind a tool the tenant already deleted.
    """
    entries: list[ToolCatalogueEntry] = []
    installed_plugins = (
        _installed_plugin_index(tenant_id, raise_on_error=True)
        if raise_on_error
        else _installed_plugin_index(tenant_id)
    )

    for provider in ToolManager.list_builtin_providers(tenant_id):
        provider_name = provider.entity.identity.name
        plugin_id = ""
        # Hardcoded built-ins return "builtin"; plugin providers return "plugin".
        # Workflow tool nodes still store plugin tools as "builtin" so the
        # studio picker and credential hydration path can resolve them.
        provider_type = provider.provider_type.value
        if isinstance(provider, PluginToolProviderController):
            if not _plugin_still_installed(provider, installed_plugins):
                continue
            plugin_id = provider.plugin_id or ""
            # Studio tool nodes and ToolManager.get_tool_runtime hydrate credentials
            # on the builtin path. ToolProviderType.PLUGIN skips that and the
            # picker cannot match plugin::... against builtin::... options.
            provider_type = "builtin"
        elif not isinstance(provider, BuiltinToolProviderController):
            # Unknown provider class — skip rather than guess.
            continue

        try:
            tools = list(provider.get_tools())
        except Exception:
            logger.exception(
                "Workflow generator: failed to list tools for provider %s",
                provider_name,
            )
            if raise_on_error:
                raise
            continue

        for tool in tools:
            try:
                tool_name = tool.entity.identity.name
                tool_label = _i18n_text(tool.entity.identity.label)
                description = _tool_description(tool.entity.description)
                entries.append(
                    _with_schema(
                        _with_search_aliases(
                            ToolCatalogueEntry(
                                provider_name=provider_name,
                                provider_type=provider_type,
                                plugin_id=plugin_id,
                                tool_name=tool_name,
                                tool_label=tool_label,
                                description=description,
                            ),
                            tool,
                        ),
                        tool,
                    )
                )
            except Exception:
                logger.exception(
                    "Workflow generator: failed to describe tool %s in provider %s",
                    getattr(getattr(tool, "entity", None), "identity", None),
                    provider_name,
                )
                if raise_on_error:
                    raise
                continue

    entries.extend(_mcp_catalogue_entries(tenant_id, raise_on_error=raise_on_error))
    entries.sort(key=itemgetter("provider_name", "tool_name"))
    if limit is None:
        return entries
    return entries[:limit]


def _mcp_catalogue_entries(tenant_id: str, *, raise_on_error: bool = False) -> list[ToolCatalogueEntry]:
    """Enumerate MCP snapshot tools. Failures skip the provider, not the catalogue."""
    try:
        providers = ToolManager.list_mcp_provider_controllers(tenant_id)
    except Exception:
        logger.exception("Workflow generator: failed to list MCP providers")
        if raise_on_error:
            raise
        return []

    entries: list[ToolCatalogueEntry] = []
    for provider in providers:
        provider_name = str(getattr(provider, "provider_id", "") or provider.entity.identity.name)
        try:
            tools = list(provider.get_tools() or [])
        except Exception:
            logger.exception("Workflow generator: failed to list MCP tools for provider %s", provider_name)
            if raise_on_error:
                raise
            continue
        for tool in tools:
            try:
                entries.append(
                    _with_schema(
                        _with_search_aliases(
                            ToolCatalogueEntry(
                                provider_name=provider_name,
                                provider_type="mcp",
                                plugin_id="",
                                tool_name=tool.entity.identity.name,
                                tool_label=_i18n_text(tool.entity.identity.label),
                                description=_tool_description(tool.entity.description),
                            ),
                            tool,
                        ),
                        tool,
                    )
                )
            except Exception:
                logger.exception(
                    "Workflow generator: failed to describe MCP tool %s in provider %s",
                    getattr(getattr(tool, "entity", None), "identity", None),
                    provider_name,
                )
                if raise_on_error:
                    raise
                continue
    return entries
