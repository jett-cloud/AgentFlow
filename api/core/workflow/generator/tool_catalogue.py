"""
Tool catalogue for the workflow generator.

Returns a compact, LLM-readable inventory of the tools currently installed for
a tenant (both hardcoded built-in providers and plugin providers). The planner
uses this to recommend ``tool`` nodes by exact ``provider/tool`` identifier;
the builder consumes the same list so it can emit a syntactically correct
``tool`` node ``data`` block (provider_id, provider_type, tool_name,
tool_label).

Format: one tool per line, ``- <provider>/<tool> — <one-line description>``.

The list is intentionally capped — if a tenant has hundreds of plugin tools,
sending the full catalogue blows past LLM context windows. We sort by
provider name and truncate to ``_MAX_TOOLS`` lines so the prompt stays
bounded. Tools beyond the cap are dropped silently; if quality suffers, the
fix is a planner-time relevance filter, not a bigger dump.

Plugin rows are intersected with the tenant's current ``management/list``
installations. The daemon tool index can outlive uninstall, which would
otherwise let Assist ``search_tools`` return a deleted plugin.
"""

import logging
from dataclasses import dataclass
from operator import itemgetter
from typing import TypedDict

from core.tools.builtin_tool.provider import BuiltinToolProviderController
from core.tools.plugin_tool.provider import PluginToolProviderController
from core.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)


_MAX_TOOLS = 80


@dataclass(frozen=True)
class _InstalledPluginIndex:
    """Live plugin installations for one tenant.

    ``None`` from ``_installed_plugin_index`` means the lookup failed and
    callers must not filter. An empty index means the tenant has no plugins,
    so daemon leftovers after uninstall must be dropped.
    """

    plugin_ids: frozenset[str]
    unique_identifiers: frozenset[str]


def _installed_plugin_index(tenant_id: str) -> _InstalledPluginIndex | None:
    """Return live installations, or ``None`` when the lookup cannot run.

    ``None`` disables filtering so a daemon outage does not empty the plugin
    catalogue. An empty index is a successful "this tenant has no plugins".
    """
    try:
        from core.plugin.impl.plugin import PluginInstaller

        plugins = PluginInstaller().list_plugins(tenant_id)
    except Exception:
        logger.exception("Workflow generator: failed to list installed plugins")
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


class ToolCatalogueEntry(TypedDict):
    provider_name: str
    provider_type: str  # "builtin" | "mcp"  (plugin providers serialize as builtin)
    plugin_id: str  # empty string for hardcoded built-ins
    tool_name: str
    tool_label: str
    description: str  # one-line LLM-friendly description


def build_tool_catalogue(
    tenant_id: str,
    *,
    limit: int | None = _MAX_TOOLS,
) -> list[ToolCatalogueEntry]:
    """
    Enumerate installed tools for the given tenant.

    Failures inside a single provider (mis-declared tool, plugin runtime
    error) are logged and skipped — one bad provider must not break the
    whole generator. When ``limit`` is an int, returns at most that many
    entries (default ``_MAX_TOOLS``). Pass ``limit=None`` for the uncapped
    list (used for the planner's complete authorization snapshot).

    Plugin providers come from the daemon tool index, which can briefly keep
    a just-uninstalled package. Cross-check against ``management/list`` so
    Assist ``search_tools`` cannot bind a tool the tenant already deleted.
    """
    entries: list[ToolCatalogueEntry] = []
    installed_plugins = _installed_plugin_index(tenant_id)

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
            continue

        for tool in tools:
            try:
                tool_name = tool.entity.identity.name
                tool_label = _i18n_text(tool.entity.identity.label)
                description = _tool_description(tool.entity.description)
                entries.append(
                    ToolCatalogueEntry(
                        provider_name=provider_name,
                        provider_type=provider_type,
                        plugin_id=plugin_id,
                        tool_name=tool_name,
                        tool_label=tool_label,
                        description=description,
                    )
                )
            except Exception:
                logger.exception(
                    "Workflow generator: failed to describe tool %s in provider %s",
                    getattr(getattr(tool, "entity", None), "identity", None),
                    provider_name,
                )
                continue

    entries.extend(_mcp_catalogue_entries(tenant_id))
    entries.sort(key=itemgetter("provider_name", "tool_name"))
    if limit is None:
        return entries
    return entries[:limit]


def _mcp_catalogue_entries(tenant_id: str) -> list[ToolCatalogueEntry]:
    """Enumerate MCP snapshot tools. Failures skip the provider, not the catalogue."""
    try:
        providers = ToolManager.list_mcp_provider_controllers(tenant_id)
    except Exception:
        logger.exception("Workflow generator: failed to list MCP providers")
        return []

    entries: list[ToolCatalogueEntry] = []
    for provider in providers:
        provider_name = str(getattr(provider, "provider_id", "") or provider.entity.identity.name)
        try:
            tools = list(provider.get_tools() or [])
        except Exception:
            logger.exception("Workflow generator: failed to list MCP tools for provider %s", provider_name)
            continue
        for tool in tools:
            try:
                entries.append(
                    ToolCatalogueEntry(
                        provider_name=provider_name,
                        provider_type="mcp",
                        plugin_id="",
                        tool_name=tool.entity.identity.name,
                        tool_label=_i18n_text(tool.entity.identity.label),
                        description=_tool_description(tool.entity.description),
                    )
                )
            except Exception:
                logger.exception(
                    "Workflow generator: failed to describe MCP tool %s in provider %s",
                    getattr(getattr(tool, "entity", None), "identity", None),
                    provider_name,
                )
                continue
    return entries


def installed_tool_keys(entries: list[ToolCatalogueEntry]) -> set[tuple[str, str]]:
    """
    Return the set of ``(provider_name, tool_name)`` pairs available for the
    tenant. The validator in ``runner.py`` consults this set so a planner /
    builder that hallucinates a tool name fails loudly at generation time
    instead of producing a runtime-broken graph.

    The set is keyed on ``provider_name`` (not ``provider_id``) because the
    builder prompt is instructed to put the provider's catalogue name into
    BOTH ``data.provider_id`` and ``data.provider_name`` on tool nodes —
    they are the same value for both built-in and plugin providers.
    """
    return {(e["provider_name"], e["tool_name"]) for e in entries}


def format_tool_catalogue(entries: list[ToolCatalogueEntry]) -> str:
    """
    Render the catalogue as a compact multi-line block for prompt injection.
    Returns an empty string when no tools are installed — callers should skip
    the section entirely in that case.
    """
    if not entries:
        return ""
    lines = []
    for e in entries:
        desc = e["description"].replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        line = f"- {e['provider_name']}/{e['tool_name']}"
        if e["provider_type"] == "mcp":
            line += " [mcp]"
        if e["tool_label"] and e["tool_label"] != e["tool_name"]:
            line += f" ({e['tool_label']})"
        if desc:
            line += f" — {desc}"
        lines.append(line)
    return "\n".join(lines)


def _i18n_text(label) -> str:
    """Pull the English label out of an I18nObject (falls back to .name)."""
    if label is None:
        return ""
    en = getattr(label, "en_US", None)
    if en:
        return en
    return getattr(label, "zh_Hans", "") or ""


def _tool_description(description) -> str:
    """Pull the LLM-facing description (``.llm``) from a ToolDescription."""
    if description is None:
        return ""
    return getattr(description, "llm", "") or ""
