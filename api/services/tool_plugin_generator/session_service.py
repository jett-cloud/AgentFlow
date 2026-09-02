from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from extensions.ext_database import db
from extensions.ext_redis import redis_client
from libs.datetime_utils import naive_utc_now
from models.tools import ToolPluginStudioSession

DRAFT_PLUGIN_NAME_RE = re.compile(r"^__draft__[0-9a-fA-F-]{8,}$")
HIDDEN_PLUGIN_NAME_PREFIX = "__hidden__"
PHASE_CREATING = "creating"
PHASE_EDITING = "editing"
SESSION_OPERATION_LOCK_SECONDS = 900
logger = logging.getLogger(__name__)


class ToolPluginStudioSessionError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_param", conflict_session_id: str | None = None) -> None:
        self.message = message
        self.code = code
        self.conflict_session_id = conflict_session_id
        super().__init__(message)


def acquire_session_operation_lock(*, tenant_id: str, account_id: str, session_id: str):
    """Acquire the cross-process lock shared by every mutation of one studio session."""
    lock = redis_client.lock(
        f"tool_plugin_studio_session:{tenant_id}:{account_id}:{session_id}",
        timeout=SESSION_OPERATION_LOCK_SECONDS,
        blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        raise ToolPluginStudioSessionError("Session is busy with another operation", code="conflict")
    return lock


def acquire_plugin_publish_lock(*, tenant_id: str, plugin_id: str):
    """Serialize ownership checks and publish side effects for one tenant/plugin identity."""
    lock = redis_client.lock(
        f"tool_plugin_publish:{tenant_id}:{plugin_id}",
        timeout=SESSION_OPERATION_LOCK_SECONDS,
        blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        raise ToolPluginStudioSessionError("Plugin is being published by another session", code="conflict")
    return lock


def release_session_operation_lock(lock: Any) -> None:
    try:
        lock.release()
    except Exception:
        # An expired lock must never turn a completed user operation into a second failure.
        logger.debug("Studio session operation lock was already released or expired", exc_info=True)


def make_draft_plugin_name() -> str:
    return f"__draft__{uuid.uuid4().hex[:12]}"


def is_draft_plugin_name(plugin_name: str) -> bool:
    return bool(DRAFT_PLUGIN_NAME_RE.match(plugin_name or ""))


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _redact_structured_credentials(value: Any) -> Any:
    """Prevent structured request credentials from ever being written to studio JSON columns."""
    if isinstance(value, list):
        return [_redact_structured_credentials(item) for item in value]
    if not isinstance(value, dict):
        return value
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        if key == "credentials" and isinstance(item, dict):
            redacted[key] = {str(name): "******" for name in item}
        else:
            redacted[key] = _redact_structured_credentials(item)
    return redacted


def is_hidden_plugin_name(plugin_name: str) -> bool:
    return (plugin_name or "").startswith(HIDDEN_PLUGIN_NAME_PREFIX)


def session_to_summary(row: ToolPluginStudioSession) -> dict[str, Any]:
    messages = row.messages
    last_text = ""
    for item in reversed(messages):
        if item.get("role") in {"user", "assistant"} and item.get("content"):
            last_text = str(item["content"])[:120]
            break
    display_name = (row.title or "").strip() or row.plugin_name
    if is_draft_plugin_name(display_name) or is_hidden_plugin_name(display_name):
        display_name = row.title or ("已隐藏会话" if row.is_hidden else "未命名插件草稿")
    if is_draft_plugin_name(row.plugin_name) and not row.title:
        display_name = "未命名插件草稿"
    return {
        "id": row.id,
        "phase": row.phase,
        "author": row.author,
        "plugin_name": row.plugin_name,
        "display_name": display_name,
        "active_tool_name": row.active_tool_name,
        "tool_names": row.tool_names,
        "plugin_status": row.plugin_status,
        "is_hidden": bool(row.is_hidden),
        "title": row.title,
        "installation_id": row.installation_id,
        "plugin_unique_identifier": row.plugin_unique_identifier,
        "revision": row.revision,
        "has_unpublished_changes": row.files != row.published_files,
        "has_files": bool(row.files),
        "last_message_preview": last_text,
        "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else str(row.updated_at),
        "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
    }


def session_to_detail(row: ToolPluginStudioSession) -> dict[str, Any]:
    detail = session_to_summary(row)
    detail.update(
        {
            "plugin_locked_at": row.plugin_locked_at.isoformat() if row.plugin_locked_at else None,
            "files": [{"path": path, "content": content} for path, content in sorted(row.files.items())],
            "messages": row.messages,
            "preview_tool": row.preview,
            "model_provider": row.model_provider,
            "model_name": row.model_name,
            "plugin_unique_identifier": row.plugin_unique_identifier,
            "installation_id": row.installation_id,
            "last_publish_diagnostic": row.last_publish_diagnostic,
        }
    )
    return detail


def list_sessions(
    *,
    tenant_id: str,
    account_id: str,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(ToolPluginStudioSession).where(
        ToolPluginStudioSession.tenant_id == tenant_id,
        ToolPluginStudioSession.account_id == account_id,
    )
    if not include_hidden:
        stmt = stmt.where(ToolPluginStudioSession.is_hidden.is_(False))
    stmt = stmt.order_by(ToolPluginStudioSession.updated_at.desc())
    rows = db.session.scalars(stmt).all()
    return [session_to_summary(row) for row in rows]


def get_session(*, tenant_id: str, account_id: str, session_id: str) -> ToolPluginStudioSession:
    row = db.session.get(ToolPluginStudioSession, session_id)
    if row is None or row.tenant_id != tenant_id or row.account_id != account_id:
        raise ToolPluginStudioSessionError("Session not found", code="not_found")
    return row


def find_by_plugin_name(*, tenant_id: str, account_id: str, plugin_name: str) -> ToolPluginStudioSession | None:
    """Return one session matching plugin_name (for lookups). Multiple sessions may share a name."""
    stmt = select(ToolPluginStudioSession).where(
        ToolPluginStudioSession.tenant_id == tenant_id,
        ToolPluginStudioSession.account_id == account_id,
        ToolPluginStudioSession.plugin_name == plugin_name,
    )
    return db.session.scalars(stmt).first()


def find_sessions_by_plugin_name(
    *,
    tenant_id: str,
    account_id: str,
    plugin_name: str,
) -> list[ToolPluginStudioSession]:
    stmt = select(ToolPluginStudioSession).where(
        ToolPluginStudioSession.tenant_id == tenant_id,
        ToolPluginStudioSession.account_id == account_id,
        ToolPluginStudioSession.plugin_name == plugin_name,
    )
    return list(db.session.scalars(stmt).all())


def create_session(
    *,
    tenant_id: str,
    account_id: str,
    author: str = "",
    plugin_name: str | None = None,
) -> ToolPluginStudioSession:
    name = (plugin_name or "").strip() or make_draft_plugin_name()
    row = ToolPluginStudioSession(
        tenant_id=tenant_id,
        account_id=account_id,
        phase=PHASE_CREATING,
        author=author or "",
        plugin_name=name,
        active_tool_name="",
        tool_names_json="[]",
        files_json="{}",
        messages_json="[]",
        plugin_status="idle",
        revision=0,
        published_files_json="{}",
    )
    db.session.add(row)
    db.session.commit()
    return row


def fork_session(
    *,
    tenant_id: str,
    account_id: str,
    source_session_id: str,
    title: str | None = None,
) -> ToolPluginStudioSession:
    """Create an independent session copying plugin files/identity from a source session."""
    from sqlalchemy.exc import IntegrityError

    source = get_session(tenant_id=tenant_id, account_id=account_id, session_id=source_session_id)
    files = dict(source.files)
    if is_draft_plugin_name(source.plugin_name) and not files:
        raise ToolPluginStudioSessionError("Cannot fork an empty draft session", code="invalid_param")

    display_plugin = source.plugin_name
    if is_draft_plugin_name(display_plugin) or is_hidden_plugin_name(display_plugin):
        display_plugin = (source.title or "").strip() or "plugin"

    fork_title = (title or "").strip() or f"新增工具 · {display_plugin}"
    fork_title = fork_title[:255]
    has_files = bool(files)
    row = ToolPluginStudioSession(
        tenant_id=tenant_id,
        account_id=account_id,
        phase=PHASE_EDITING if has_files else PHASE_CREATING,
        author=source.author or "",
        plugin_name=source.plugin_name,
        active_tool_name=source.active_tool_name or "",
        tool_names_json=_dump(source.tool_names),
        files_json=_dump(files),
        messages_json="[]",
        # Fork is an independent draft workspace — do not share daemon install identity.
        plugin_status="draft_ready" if has_files else "idle",
        preview_json=source.preview_json,
        model_provider=source.model_provider,
        model_name=source.model_name,
        plugin_unique_identifier=None,
        installation_id=None,
        is_hidden=False,
        title=fork_title,
        plugin_locked_at=naive_utc_now() if has_files else None,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ToolPluginStudioSessionError(
            "无法复制会话：数据库仍限制同名插件只能有一个会话，请先执行迁移 "
            "drop unique_tool_plugin_studio_session_plugin（revision e7f6a5b4c3d2）",
            code="conflict",
        ) from exc
    return row


def _ensure_unlocked_for_rename(row: ToolPluginStudioSession) -> None:
    if row.phase == PHASE_EDITING or row.plugin_locked_at is not None:
        raise ToolPluginStudioSessionError("Plugin name and author are locked for this session")


def update_session(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    patch: dict[str, Any],
    expected_revision: int | None = None,
) -> ToolPluginStudioSession:
    """Apply a session patch and reject stale writers using the persisted revision."""
    row = get_session(tenant_id=tenant_id, account_id=account_id, session_id=session_id)
    if expected_revision is not None and row.revision != expected_revision:
        raise ToolPluginStudioSessionError(
            f"Session revision conflict: expected {expected_revision}, current {row.revision}",
            code="conflict",
        )

    if "plugin_name" in patch or "author" in patch:
        new_plugin_name = str(patch.get("plugin_name", row.plugin_name)).strip()
        new_author = str(patch.get("author", row.author))
        if new_plugin_name != row.plugin_name or new_author != row.author:
            _ensure_unlocked_for_rename(row)
        if new_plugin_name != row.plugin_name:
            row.plugin_name = new_plugin_name
        row.author = new_author

    if "active_tool_name" in patch:
        row.active_tool_name = str(patch.get("active_tool_name") or "")
    if "tool_names" in patch:
        names = patch.get("tool_names") or []
        if not isinstance(names, list):
            raise ToolPluginStudioSessionError("tool_names must be a list")
        row.tool_names_json = _dump([str(item) for item in names])
    if "files" in patch:
        files = patch["files"]
        if isinstance(files, list):
            mapping = {str(item["path"]): str(item.get("content") or "") for item in files if isinstance(item, dict)}
        elif isinstance(files, dict):
            mapping = {str(path): str(content) for path, content in files.items()}
        else:
            raise ToolPluginStudioSessionError("files must be a list or object")
        row.files_json = _dump(mapping)
        if mapping and row.plugin_locked_at is None:
            lock_session_after_first_files(row)
    if "messages" in patch:
        messages = patch.get("messages") or []
        if not isinstance(messages, list):
            raise ToolPluginStudioSessionError("messages must be a list")
        row.messages_json = _dump(_redact_structured_credentials(messages))
    if "preview_tool" in patch:
        preview = patch.get("preview_tool")
        row.preview_json = _dump(_redact_structured_credentials(preview)) if preview is not None else None
    if "model_provider" in patch:
        row.model_provider = patch.get("model_provider")
    if "model_name" in patch:
        row.model_name = patch.get("model_name")
    if "plugin_unique_identifier" in patch:
        row.plugin_unique_identifier = patch.get("plugin_unique_identifier")
    if "installation_id" in patch:
        row.installation_id = patch.get("installation_id")
    if "plugin_status" in patch:
        row.plugin_status = str(patch.get("plugin_status") or row.plugin_status)
    if "title" in patch:
        title = patch.get("title")
        row.title = str(title).strip() if title is not None else None
    if "published_files" in patch:
        published_files = patch.get("published_files") or {}
        if not isinstance(published_files, dict):
            raise ToolPluginStudioSessionError("published_files must be an object")
        row.published_files_json = _dump(
            {str(path): str(content) for path, content in published_files.items()}
        )
    if "last_publish_diagnostic" in patch:
        diagnostic = patch.get("last_publish_diagnostic")
        row.last_publish_diagnostic_json = _dump(diagnostic) if diagnostic is not None else None

    row.revision += 1
    row.updated_at = naive_utc_now()
    db.session.add(row)
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ToolPluginStudioSessionError("Session was updated by another request", code="conflict") from exc
    return row


def lock_session_after_first_files(row: ToolPluginStudioSession) -> None:
    if row.plugin_locked_at is not None:
        return
    if is_draft_plugin_name(row.plugin_name):
        raise ToolPluginStudioSessionError("Set a real plugin_name before generating files")
    row.phase = PHASE_EDITING
    row.plugin_locked_at = naive_utc_now()


def delete_session(*, tenant_id: str, account_id: str, session_id: str) -> None:
    row = get_session(tenant_id=tenant_id, account_id=account_id, session_id=session_id)
    db.session.delete(row)
    db.session.commit()


def list_sessions_by_installation(
    *,
    tenant_id: str,
    account_id: str,
    installation_id: str | None = None,
    plugin_unique_identifier: str | None = None,
) -> list[dict[str, Any]]:
    """Return studio sessions linked to an installed plugin for uninstall confirmations."""
    if not installation_id and not plugin_unique_identifier:
        return []
    stmt = select(ToolPluginStudioSession).where(
        ToolPluginStudioSession.tenant_id == tenant_id,
        ToolPluginStudioSession.account_id == account_id,
    )
    rows = list(db.session.scalars(stmt).all())
    matched: list[ToolPluginStudioSession] = []
    for row in rows:
        if installation_id and row.installation_id == installation_id:
            matched.append(row)
            continue
        if plugin_unique_identifier and row.plugin_unique_identifier == plugin_unique_identifier:
            matched.append(row)
    result: list[dict[str, Any]] = []
    for row in matched:
        summary = session_to_summary(row)
        summary["message_count"] = len(row.messages or [])
        summary["installation_id"] = row.installation_id
        summary["plugin_unique_identifier"] = row.plugin_unique_identifier
        result.append(summary)
    return result


def delete_sessions_by_installation(
    *,
    tenant_id: str,
    account_id: str,
    installation_id: str | None = None,
    plugin_unique_identifier: str | None = None,
) -> list[str]:
    """Delete studio sessions linked to an installation. Returns deleted session ids."""
    summaries = list_sessions_by_installation(
        tenant_id=tenant_id,
        account_id=account_id,
        installation_id=installation_id,
        plugin_unique_identifier=plugin_unique_identifier,
    )
    deleted_ids: list[str] = []
    for item in summaries:
        session_id = str(item["id"])
        delete_session(tenant_id=tenant_id, account_id=account_id, session_id=session_id)
        deleted_ids.append(session_id)
    return deleted_ids


def hide_session(*, tenant_id: str, account_id: str, session_id: str) -> ToolPluginStudioSession:
    row = get_session(tenant_id=tenant_id, account_id=account_id, session_id=session_id)
    if row.is_hidden:
        return row
    if not row.title:
        row.title = row.plugin_name if not is_draft_plugin_name(row.plugin_name) else "未命名插件草稿"
    # Legacy rows may still use __hidden__{id} as plugin_name; leave real names intact.
    row.is_hidden = True
    row.revision += 1
    row.updated_at = naive_utc_now()
    db.session.add(row)
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ToolPluginStudioSessionError("Session was updated by another request", code="conflict") from exc
    return row


def unhide_session(*, tenant_id: str, account_id: str, session_id: str) -> ToolPluginStudioSession:
    row = get_session(tenant_id=tenant_id, account_id=account_id, session_id=session_id)
    if not row.is_hidden:
        return row
    # Compat: older hide() rewrote plugin_name to __hidden__{id}; restore from title.
    if is_hidden_plugin_name(row.plugin_name):
        restore_name = (row.title or "").strip()
        if not restore_name or restore_name == "未命名插件草稿":
            restore_name = make_draft_plugin_name()
        row.plugin_name = restore_name
    row.is_hidden = False
    row.revision += 1
    row.updated_at = naive_utc_now()
    db.session.add(row)
    try:
        db.session.commit()
    except StaleDataError as exc:
        db.session.rollback()
        raise ToolPluginStudioSessionError("Session was updated by another request", code="conflict") from exc
    return row


def persist_turn_result(
    *,
    tenant_id: str,
    account_id: str,
    session_id: str,
    files: dict[str, str],
    messages: list[dict[str, Any]],
    preview_tool: dict[str, Any] | None,
    plugin_unique_identifier: str | None,
    installation_id: str | None,
    plugin_status: str | None,
    active_tool_name: str | None = None,
    author: str | None = None,
    plugin_name: str | None = None,
    expected_revision: int | None = None,
) -> ToolPluginStudioSession:
    tool_names = sorted(
        {
            path.removeprefix("tools/").removesuffix(".yaml").removesuffix(".yml")
            for path in files
            if path.startswith("tools/") and path.endswith((".yaml", ".yml"))
        }
    )
    patch: dict[str, Any] = {
        "files": files,
        "messages": messages,
        "preview_tool": preview_tool,
        "tool_names": tool_names,
    }
    if active_tool_name is not None:
        patch["active_tool_name"] = active_tool_name
    if author is not None:
        patch["author"] = author
    if plugin_name is not None:
        patch["plugin_name"] = plugin_name
    if plugin_unique_identifier is not None:
        patch["plugin_unique_identifier"] = plugin_unique_identifier
    if installation_id is not None:
        patch["installation_id"] = installation_id
    if plugin_status is not None:
        patch["plugin_status"] = plugin_status
    return update_session(
        tenant_id=tenant_id,
        account_id=account_id,
        session_id=session_id,
        patch=patch,
        expected_revision=expected_revision,
    )
