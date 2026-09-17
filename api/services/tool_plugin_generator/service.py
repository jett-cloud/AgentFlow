from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.app.entities.app_invoke_entities import InvokeFrom
from core.app.file_access import DatabaseFileAccessController
from core.plugin.entities.plugin_daemon import PluginInstallTaskStartResponse, PluginInstallTaskStatus
from core.plugin.plugin_service import PluginService
from core.tools.__base.tool_runtime import ToolRuntime
from core.tools.entities.tool_entities import ToolInvokeFrom, ToolInvokeMessage, ToolParameter, ToolProviderType
from core.tools.errors import ToolProviderNotFoundError
from core.tools.tool_engine import ToolEngine
from core.tools.tool_manager import ToolManager
from extensions.ext_database import db
from factories.file_factory import build_from_mapping, build_from_mappings
from services.tool_plugin_generator.llm_fill import LLMFillClient, build_fill_prompt, parse_llm_fill_payload
from services.tool_plugin_generator.packager import (
    PluginPackagingError,
    normalize_plugin_source_files,
    package_plugin_files,
)
from services.tool_plugin_generator.preview_mapper import map_files_to_preview_tool, normalize_plugin_provider_id
from services.tool_plugin_generator.scaffold import render_scaffold
from services.tool_plugin_generator.validator import ToolPluginValidationError, validate_plugin_files

logger = logging.getLogger(__name__)

_file_access_controller = DatabaseFileAccessController()
_FILE_PARAMETER_TYPES = {
    ToolParameter.ToolParameterType.FILE,
    ToolParameter.ToolParameterType.FILES,
    ToolParameter.ToolParameterType.SYSTEM_FILES,
}
_SUCCESS_MESSAGE_TYPES = {
    ToolInvokeMessage.MessageType.IMAGE,
    ToolInvokeMessage.MessageType.IMAGE_LINK,
    ToolInvokeMessage.MessageType.BLOB,
    ToolInvokeMessage.MessageType.BLOB_CHUNK,
    ToolInvokeMessage.MessageType.FILE,
    ToolInvokeMessage.MessageType.BINARY_LINK,
    ToolInvokeMessage.MessageType.LINK,
}
_FAILURE_TEXT_PREFIXES = (
    "request failed:",
    "api request failed:",
    "api error",
    "failed to read file:",
    "failed to",
    "error:",
    "unsupported ",
    "no image file",
    "please check",
    "could not read",
    "api key is missing",
)


class ToolPluginInstallError(Exception):
    """Raised when plugin packaging/install does not become ready."""

    def __init__(self, message: str, *, plugin_unique_identifier: str | None = None) -> None:
        self.message = message
        self.plugin_unique_identifier = plugin_unique_identifier
        super().__init__(message)


class ToolPluginOwnershipError(ToolPluginInstallError):
    """Raised when a same-name installation is not owned by the publishing studio session."""


@dataclass
class GenerateResult:
    files: dict[str, str]
    preview_tool: dict[str, Any]


@dataclass
class InstallResult:
    plugin_unique_identifier: str
    task: PluginInstallTaskStartResponse
    installation_id: str | None = None


@dataclass
class TestToolPluginResult:
    ok: bool
    output_text: str
    error: str | None
    elapsed_ms: int
    plugin_unique_identifier: str | None = None


@dataclass
class UninstallByPluginIdResult:
    plugin_id: str
    uninstalled_installation_ids: list[str]
    failed_installation_ids: list[str]


def plugin_id_from_unique_identifier(plugin_unique_identifier: str) -> str:
    """Extract plugin_id from `author/name:version@checksum` unique identifiers."""
    base = str(plugin_unique_identifier or "").split("@", 1)[0]
    if ":" in base:
        return base.rsplit(":", 1)[0]
    return base


def plugin_cwd_relpath_from_unique_identifier(plugin_unique_identifier: str) -> str:
    """Map `author/name:version@checksum` to daemon cwd folder `author/name-version@checksum`."""
    text = str(plugin_unique_identifier or "").strip()
    if not text:
        return ""
    if "@" in text:
        base, checksum = text.split("@", 1)
    else:
        base, checksum = text, ""
    if ":" in base:
        name_part, version = base.rsplit(":", 1)
        dirname = f"{name_part}-{version}"
    else:
        dirname = base
    return f"{dirname}@{checksum}" if checksum else dirname


def _plugin_daemon_host_cwd_root() -> Path | None:
    """Resolve host path for plugin_daemon cwd volume when API can see it."""
    for key in ("PLUGIN_DAEMON_HOST_CWD", "DIFY_PLUGIN_DAEMON_CWD"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            path = Path(raw)
            return path if path.is_dir() else None
    # api/services/tool_plugin_generator/service.py -> repo root
    candidate = Path(__file__).resolve().parents[3] / "docker" / "volumes" / "plugin_daemon" / "cwd"
    return candidate if candidate.is_dir() else None


def purge_plugin_cwd_for_unique_identifier(plugin_unique_identifier: str) -> bool:
    """Delete leftover daemon cwd for a unique identifier (failed installs leave empty .venv)."""
    root = _plugin_daemon_host_cwd_root()
    rel = plugin_cwd_relpath_from_unique_identifier(plugin_unique_identifier)
    if root is None or not rel:
        return False
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return False
    if not target.is_dir():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return not target.exists()


def _list_installed_plugins(*, tenant_id: str, page_size: int = 100) -> list[Any]:
    """Page through daemon plugin list instead of only the first 256 entries."""
    collected: list[Any] = []
    page = 1
    while page <= 100:
        response = PluginService.list_with_total(
            tenant_id,
            "",
            page,
            page_size,
        )
        batch = list(getattr(response, "list", None) or [])
        if not batch:
            break
        collected.extend(batch)
        total = getattr(response, "total", None)
        if isinstance(total, int):
            if len(collected) >= total:
                break
        elif len(batch) < page_size:
            break
        page += 1
    return collected


def _plugin_recency_key(plugin: Any) -> Any:
    return getattr(plugin, "created_at", None) or getattr(plugin, "updated_at", None) or 0


def _pick_installation_id(
    plugins: list[Any],
    *,
    plugin_unique_identifier: str,
    plugin_id: str,
) -> str | None:
    for plugin in plugins:
        if getattr(plugin, "plugin_unique_identifier", None) == plugin_unique_identifier:
            installation_id = getattr(plugin, "installation_id", None) or getattr(plugin, "id", None)
            if installation_id:
                return str(installation_id)

    del plugin_id
    return None


def uninstall_installations_for_plugin_id(
    *,
    tenant_id: str,
    plugin_id: str,
    exclude_unique_identifiers: set[str] | None = None,
) -> UninstallByPluginIdResult:
    """Uninstall installations matching plugin_id, optionally skipping listed unique identifiers."""
    plugin_id = str(plugin_id or "").strip()
    excluded = {str(item) for item in (exclude_unique_identifiers or set()) if str(item).strip()}
    if not plugin_id:
        return UninstallByPluginIdResult(
            plugin_id=plugin_id,
            uninstalled_installation_ids=[],
            failed_installation_ids=[],
        )

    try:
        plugins = _list_installed_plugins(tenant_id=tenant_id)
    except Exception:
        logger.warning(
            "Failed to list plugins while uninstalling by plugin_id=%s tenant=%s",
            plugin_id,
            tenant_id,
            exc_info=True,
        )
        return UninstallByPluginIdResult(
            plugin_id=plugin_id,
            uninstalled_installation_ids=[],
            failed_installation_ids=[],
        )

    uninstalled: list[str] = []
    failed: list[str] = []
    seen: set[str] = set()
    for plugin in plugins:
        if getattr(plugin, "plugin_id", None) != plugin_id:
            continue
        unique_identifier = str(getattr(plugin, "plugin_unique_identifier", None) or "")
        if unique_identifier and unique_identifier in excluded:
            continue
        installation_id = getattr(plugin, "installation_id", None) or getattr(plugin, "id", None)
        if not installation_id:
            continue
        installation_id = str(installation_id)
        if installation_id in seen:
            continue
        seen.add(installation_id)
        try:
            if PluginService.uninstall(tenant_id, installation_id):
                uninstalled.append(installation_id)
            else:
                failed.append(installation_id)
                logger.warning(
                    "Plugin uninstall returned false installation_id=%s plugin_id=%s tenant=%s",
                    installation_id,
                    plugin_id,
                    tenant_id,
                )
        except Exception:
            failed.append(installation_id)
            logger.warning(
                "Failed to uninstall installation_id=%s plugin_id=%s tenant=%s",
                installation_id,
                plugin_id,
                tenant_id,
                exc_info=True,
            )

    return UninstallByPluginIdResult(
        plugin_id=plugin_id,
        uninstalled_installation_ids=uninstalled,
        failed_installation_ids=failed,
    )


def uninstall_plugin_unique_identifier(*, tenant_id: str, plugin_unique_identifier: str) -> bool:
    """Uninstall only installations with the exact package identifier; never match by plugin_id."""
    try:
        plugins = _list_installed_plugins(tenant_id=tenant_id)
    except Exception:
        logger.warning(
            "Failed to inspect exact plugin during rollback tenant=%s identifier=%s",
            tenant_id,
            plugin_unique_identifier,
            exc_info=True,
        )
        return False
    for plugin in plugins:
        if getattr(plugin, "plugin_unique_identifier", None) != plugin_unique_identifier:
            continue
        installation_id = getattr(plugin, "installation_id", None) or getattr(plugin, "id", None)
        if not installation_id:
            continue
        try:
            if not PluginService.uninstall(tenant_id, str(installation_id)):
                return False
        except Exception:
            logger.warning(
                "Failed to uninstall exact rollback candidate tenant=%s installation_id=%s",
                tenant_id,
                installation_id,
                exc_info=True,
            )
            return False
    return True


def _installation_id_for_unique_identifier(
    plugins: list[Any],
    *,
    plugin_unique_identifier: str,
) -> str | None:
    """Return installation_id only when the exact unique identifier is already installed."""
    for plugin in plugins:
        if getattr(plugin, "plugin_unique_identifier", None) != plugin_unique_identifier:
            continue
        installation_id = getattr(plugin, "installation_id", None) or getattr(plugin, "id", None)
        if installation_id:
            return str(installation_id)
    return None


def enrich_install_error_message(message: str) -> str:
    """Append recovery guidance for broken plugin cwd/.venv launches."""
    text = str(message or "").strip() or "Plugin install failed"
    lowered = text.lower()
    if "missing 1 required positional argument: 'config'" in lowered or "plugin.__init__()" in lowered:
        return (
            f"{text}\n"
            "main.py must use `plugin = Plugin(DifyPluginEnv())` (not bare `Plugin()`). "
            "Studio auto-rewrites this on the next「重新安装」."
        )
    if "toolproviderconfiguration" in lowered or (
        "extra" in lowered and "field required" in lowered
    ):
        return (
            f"{text}\n"
            "provider/*.yaml is missing required `extra.python.source` (and usually `tools:`). "
            "Studio auto-fills these on the next「重新安装」."
        )
    if any(
        marker in lowered
        for marker in (
            "gevent",
            "failed to install dependencies",
            "failed to init environment",
            "brokenpipe",
            "broken pipe",
            "llmpollingresult",
            "cannot import name",
            "no module named 'dify_plugin",
        )
    ):
        return (
            f"{text}\n"
            "cwd/.venv may be incomplete (uv deps timed out or network broken). "
            "Raise PLUGIN_PYTHON_ENV_INIT_TIMEOUT (e.g. 600), optionally set PIP_MIRROR_URL, "
            "stop plugin_daemon, delete the matching directory under docker/volumes/plugin_daemon/cwd "
            "(and cwd/.uv-cache if needed), then Studio「重新安装」."
        )
    return text


def resolve_installation_id(
    *,
    tenant_id: str,
    plugin_unique_identifier: str,
    max_attempts: int = 5,
    interval_seconds: float = 1.0,
    page_size: int = 100,
) -> str | None:
    """Look up installation_id for a freshly installed plugin unique identifier."""
    plugin_id = plugin_id_from_unique_identifier(plugin_unique_identifier)
    for attempt in range(max_attempts):
        try:
            plugins = _list_installed_plugins(tenant_id=tenant_id, page_size=page_size)
        except Exception:
            logger.warning(
                "Failed to list plugins while resolving installation_id tenant=%s identifier=%s",
                tenant_id,
                plugin_unique_identifier,
                exc_info=True,
            )
            plugins = []

        installation_id = _pick_installation_id(
            plugins,
            plugin_unique_identifier=plugin_unique_identifier,
            plugin_id=plugin_id,
        )
        if installation_id:
            return installation_id
        if attempt + 1 < max_attempts:
            time.sleep(interval_seconds)
    return None


def wait_for_install_task(
    *,
    tenant_id: str,
    task_start: Any,
    max_attempts: int = 90,
    interval_seconds: float = 2.0,
) -> Any:
    """Block until the async plugin install task succeeds, fails, or times out."""
    if getattr(task_start, "all_installed", False):
        return getattr(task_start, "task", None)

    task_id = str(getattr(task_start, "task_id", "") or "").strip()
    if not task_id:
        raise ToolPluginInstallError("Install task id missing from plugin daemon response")

    last_task: Any = None
    for _ in range(max_attempts):
        last_task = PluginService.fetch_install_task(tenant_id, task_id)
        status = getattr(last_task, "status", None)
        status_value = str(getattr(status, "value", status) or "").lower()
        if status == PluginInstallTaskStatus.Success or status_value == "success":
            return last_task
        if status == PluginInstallTaskStatus.Failed or status_value == "failed":
            failed_message = "Plugin install task failed"
            for item in getattr(last_task, "plugins", None) or []:
                item_status = str(getattr(getattr(item, "status", None), "value", getattr(item, "status", ""))).lower()
                if item_status == "failed":
                    failed_message = str(getattr(item, "message", None) or failed_message)
                    break
            raise ToolPluginInstallError(enrich_install_error_message(failed_message))
        time.sleep(interval_seconds)

    raise ToolPluginInstallError("Plugin install timed out before the daemon reported success")


def interpret_tool_test_messages(
    messages: list[ToolInvokeMessage],
    *,
    output_text: str,
) -> tuple[bool, str | None]:
    """Decide sandbox ok/error from invoke messages (plugins often yield errors as TEXT)."""
    if not messages:
        return False, "No output from tool"

    for message in messages:
        if message.type is ToolInvokeMessage.MessageType.LOG:
            log = message.message
            status = getattr(log, "status", None)
            status_value = str(getattr(status, "value", status) or "").lower()
            if status_value == "error":
                return False, str(getattr(log, "error", None) or output_text or "Tool log reported error")
        if message.type in _SUCCESS_MESSAGE_TYPES:
            return True, None

    text = (output_text or "").strip()
    if not text:
        return False, "No output from tool"

    lowered = text.lower()
    if any(lowered.startswith(prefix) or f"\n{prefix}" in lowered for prefix in _FAILURE_TEXT_PREFIXES):
        return False, text
    return True, None


def generate_tool_plugin(
    *,
    author: str,
    plugin_name: str,
    tool_name: str,
    user_prompt: str,
    api_doc: str,
    llm_client: LLMFillClient,
    on_llm_event: Callable[[str], None] | None = None,
) -> GenerateResult:
    prompt = build_fill_prompt(
        author=author,
        plugin_name=plugin_name,
        tool_name=tool_name,
        user_prompt=user_prompt,
        api_doc=api_doc,
    )
    if on_llm_event is None:
        llm_payload = llm_client.complete(prompt)
    else:
        llm_payload = llm_client.complete(prompt, on_event=on_llm_event)
    fill = parse_llm_fill_payload(llm_payload)
    files = render_scaffold(
        author=author,
        plugin_name=plugin_name,
        tool_name=tool_name,
        fill=fill,
    )
    validate_plugin_files(files)
    preview_tool = map_files_to_preview_tool(files, author=author, plugin_name=plugin_name)
    return GenerateResult(files=files, preview_tool=preview_tool)


def install_tool_plugin(
    *,
    files: dict[str, str],
    tenant_id: str,
    user_id: str,
    previous_installation_id: str | None = None,
) -> InstallResult:
    """Install a candidate only when every same-name installation is owned by this session."""
    del user_id  # reserved for audit / future ownership checks
    try:
        files = normalize_plugin_source_files(files)
        validate_plugin_files(files)
        package = package_plugin_files(files)
        decoded = PluginService.upload_pkg(tenant_id, package)
    except ToolPluginValidationError:
        raise
    except PluginPackagingError as exc:
        raise ToolPluginInstallError(str(exc)) from exc
    except Exception as exc:
        detail = str(exc).strip()
        message = "Unable to prepare candidate plugin package"
        if detail:
            message = f"{message}: {detail}"
        raise ToolPluginInstallError(message) from exc
    plugin_unique_identifier = str(decoded.unique_identifier)
    plugin_id = plugin_id_from_unique_identifier(plugin_unique_identifier)

    try:
        installed_plugins = _list_installed_plugins(tenant_id=tenant_id)
    except Exception as exc:
        raise ToolPluginInstallError(
            "Unable to verify existing plugin ownership before install",
            plugin_unique_identifier=plugin_unique_identifier,
        ) from exc

    same_plugin_installations: set[str] = set()
    for plugin in installed_plugins:
        if getattr(plugin, "plugin_id", None) != plugin_id:
            continue
        installation_id = getattr(plugin, "installation_id", None) or getattr(plugin, "id", None)
        if installation_id:
            same_plugin_installations.add(str(installation_id))

    if same_plugin_installations:
        if not previous_installation_id or same_plugin_installations != {previous_installation_id}:
            raise ToolPluginOwnershipError(
                f"Plugin {plugin_id} is already installed outside this studio session",
                plugin_unique_identifier=plugin_unique_identifier,
            )
        try:
            removed = PluginService.uninstall(tenant_id, previous_installation_id)
        except Exception as exc:
            raise ToolPluginInstallError(
                "Failed to uninstall the session-owned previous plugin",
                plugin_unique_identifier=plugin_unique_identifier,
            ) from exc
        if not removed:
            raise ToolPluginInstallError(
                "Failed to uninstall the session-owned previous plugin",
                plugin_unique_identifier=plugin_unique_identifier,
            )
        time.sleep(1)

    # Failed installs can leave a reusable but incomplete cwd/.venv. Rebuild the exact candidate.
    purge_plugin_cwd_for_unique_identifier(plugin_unique_identifier)
    if same_plugin_installations:
        decoded = PluginService.upload_pkg(tenant_id, package)
        plugin_unique_identifier = str(decoded.unique_identifier)

    try:
        task_start = PluginService.install_from_local_pkg(tenant_id, [plugin_unique_identifier])
        wait_for_install_task(tenant_id=tenant_id, task_start=task_start)
    except ToolPluginInstallError as exc:
        raise ToolPluginInstallError(
            enrich_install_error_message(exc.message),
            plugin_unique_identifier=plugin_unique_identifier,
        ) from exc
    except Exception as exc:
        raise ToolPluginInstallError(
            enrich_install_error_message(str(exc)),
            plugin_unique_identifier=plugin_unique_identifier,
        ) from exc

    installation_id = resolve_installation_id(
        tenant_id=tenant_id,
        plugin_unique_identifier=plugin_unique_identifier,
    )
    if not installation_id:
        raise ToolPluginInstallError(
            "Plugin install finished but its exact installation_id was not found",
            plugin_unique_identifier=plugin_unique_identifier,
        )

    if isinstance(task_start, PluginInstallTaskStartResponse):
        # Keep the original task payload shape for API clients; only flip readiness.
        task = PluginInstallTaskStartResponse(
            all_installed=True,
            task_id=task_start.task_id,
            task=task_start.task,
        )
    else:
        task = task_start

    return InstallResult(
        plugin_unique_identifier=plugin_unique_identifier,
        task=task,
        installation_id=installation_id,
    )


def _resolve_tool_runtime_for_test(
    *,
    tenant_id: str,
    user_id: str,
    provider_id: str,
    tool_name: str,
    credentials: dict[str, Any] | None,
    allow_workspace_credentials: bool,
):
    """Build a tool runtime with inline credentials, else workspace BUILT_IN defaults, else empty PLUGIN."""
    provider_id = normalize_plugin_provider_id(provider_id)
    cleaned = {
        str(key): value
        for key, value in (credentials or {}).items()
        if value is not None and str(value).strip() != ""
    }

    if cleaned:
        plugin_tool = ToolManager.get_tool_runtime(
            provider_type=ToolProviderType.PLUGIN,
            provider_id=provider_id,
            tool_name=tool_name,
            tenant_id=tenant_id,
            user_id=user_id,
            invoke_from=InvokeFrom.DEBUGGER,
            tool_invoke_from=ToolInvokeFrom.WORKFLOW,
        )
        return plugin_tool.fork_tool_runtime(
            ToolRuntime(
                tenant_id=tenant_id,
                user_id=user_id,
                credentials=cleaned,
                invoke_from=InvokeFrom.DEBUGGER,
                tool_invoke_from=ToolInvokeFrom.WORKFLOW,
            )
        )

    if not allow_workspace_credentials:
        plugin_tool = ToolManager.get_tool_runtime(
            provider_type=ToolProviderType.PLUGIN,
            provider_id=provider_id,
            tool_name=tool_name,
            tenant_id=tenant_id,
            user_id=user_id,
            invoke_from=InvokeFrom.DEBUGGER,
            tool_invoke_from=ToolInvokeFrom.WORKFLOW,
        )
        return plugin_tool.fork_tool_runtime(
            ToolRuntime(
                tenant_id=tenant_id,
                user_id=user_id,
                credentials={},
                invoke_from=InvokeFrom.DEBUGGER,
                tool_invoke_from=ToolInvokeFrom.WORKFLOW,
            )
        )

    try:
        return ToolManager.get_tool_runtime(
            provider_type=ToolProviderType.BUILT_IN,
            provider_id=provider_id,
            tool_name=tool_name,
            tenant_id=tenant_id,
            user_id=user_id,
            invoke_from=InvokeFrom.DEBUGGER,
            tool_invoke_from=ToolInvokeFrom.WORKFLOW,
        )
    except ToolProviderNotFoundError:
        logger.info(
            "No workspace credentials for provider=%s; falling back to empty PLUGIN runtime",
            provider_id,
        )
    except Exception:
        logger.info(
            "BUILT_IN credential lookup failed for provider=%s; falling back to PLUGIN",
            provider_id,
            exc_info=True,
        )

    return ToolManager.get_tool_runtime(
        provider_type=ToolProviderType.PLUGIN,
        provider_id=provider_id,
        tool_name=tool_name,
        tenant_id=tenant_id,
        user_id=user_id,
        invoke_from=InvokeFrom.DEBUGGER,
        tool_invoke_from=ToolInvokeFrom.WORKFLOW,
    )


def _is_file_mapping(value: Any) -> bool:
    return isinstance(value, dict) and bool(value.get("transfer_method"))


def hydrate_tool_file_parameters(
    *,
    runtime: Any,
    tenant_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Convert sandbox/workflow file mappings into graphon File objects for plugin invoke."""
    hydrated = dict(parameters)
    entity = getattr(runtime, "entity", None)
    schema_parameters = getattr(entity, "parameters", None) if entity is not None else None
    if not isinstance(schema_parameters, list):
        return hydrated

    for parameter in schema_parameters:
        name = getattr(parameter, "name", None)
        param_type = getattr(parameter, "type", None)
        if not name or name not in hydrated or param_type not in _FILE_PARAMETER_TYPES:
            continue

        value = hydrated[name]
        if param_type is ToolParameter.ToolParameterType.FILE:
            if not _is_file_mapping(value):
                continue
            hydrated[name] = build_from_mapping(
                mapping=value,
                tenant_id=tenant_id,
                access_controller=_file_access_controller,
            )
            continue

        mappings: list[dict[str, Any]]
        if _is_file_mapping(value):
            mappings = [value]
        elif isinstance(value, list) and all(_is_file_mapping(item) for item in value):
            mappings = value
        else:
            continue
        hydrated[name] = build_from_mappings(
            mappings=mappings,
            tenant_id=tenant_id,
            access_controller=_file_access_controller,
        )

    return hydrated


def test_tool_plugin(
    *,
    tenant_id: str,
    user_id: str,
    provider_id: str,
    tool_name: str,
    parameters: dict[str, Any],
    credentials: dict[str, Any] | None,
    allow_workspace_credentials: bool,
) -> TestToolPluginResult:
    """Invoke an installed plugin tool through the same runtime used by workflow tool nodes."""
    started_at = time.monotonic()
    # Legacy studio sessions stored org/plugin; Dify runtime requires org/plugin/provider.
    provider_id = normalize_plugin_provider_id(provider_id)
    plugin_unique_identifier: str | None = None
    try:
        runtime = _resolve_tool_runtime_for_test(
            tenant_id=tenant_id,
            user_id=user_id,
            provider_id=provider_id,
            tool_name=tool_name,
            credentials=credentials,
            allow_workspace_credentials=allow_workspace_credentials,
        )
        raw_identifier = getattr(runtime, "plugin_unique_identifier", None)
        if raw_identifier:
            plugin_unique_identifier = str(raw_identifier)
        tool_parameters = hydrate_tool_file_parameters(
            runtime=runtime,
            tenant_id=tenant_id,
            parameters=dict(parameters),
        )
        messages = list(
            runtime.invoke(
                session=db.session(),
                user_id=user_id,
                tool_parameters=tool_parameters,
            )
        )
        output_text = ToolEngine.tool_response_to_str(messages)
        ok, error = interpret_tool_test_messages(messages, output_text=output_text)
        return TestToolPluginResult(
            ok=ok,
            output_text=output_text,
            error=error,
            elapsed_ms=round((time.monotonic() - started_at) * 1000),
            plugin_unique_identifier=plugin_unique_identifier,
        )
    except Exception as exc:
        logger.warning(
            "Tool plugin test invocation failed for tenant=%s provider=%s tool=%s",
            tenant_id,
            provider_id,
            tool_name,
        )
        return TestToolPluginResult(
            ok=False,
            output_text="",
            error=str(exc),
            elapsed_ms=round((time.monotonic() - started_at) * 1000),
            plugin_unique_identifier=plugin_unique_identifier,
        )
