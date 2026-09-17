"""Parse selectors and references without mutating graph data."""

import logging
import re
from typing import Any

from core.workflow.generator.types import WorkflowGenerationMode

logger = logging.getLogger(__name__)


_VAR_REF_RE = re.compile(
    r"\{\{#([a-zA-Z0-9_]{1,50})\.([a-zA-Z_][a-zA-Z0-9_]{0,29}(?:\.[a-zA-Z_][a-zA-Z0-9_]{0,29}){0,9})#\}\}"
)


_LENIENT_VAR_REF_RE = re.compile(r"\{\{#([^#.{}]+)\.([^#]+)#\}\}")


_INVALID_ID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_]")


_ID_FIELDS = frozenset({"start_node_id", "iteration_id", "loop_id", "parentId"})


_NON_SELECTOR_LIST_KEYS = frozenset(
    {
        "options",
        "required",
        "dataset_ids",
        "allowed_file_types",
        "allowed_file_extensions",
        "allowed_file_upload_methods",
        "classes",
    }
)


_SELECTOR_KEYS = frozenset(
    {
        "selector",
        "value_selector",
        "variable_selector",
        "iterator_selector",
        "query_variable_selector",
        "query_attachment_selector",
        "output_selector",
        "variable",
        "file",
    }
)


_CONTAINER_SCOPE_VARS = frozenset({"item", "index"})


_PE_BUILTIN_OUTPUTS = ("__is_success", "__reason", "__usage")


_HITL_BUILTIN_OUTPUTS = ("__action_id", "__action_value", "__rendered_content")


_ARRAY_OUTPUT_TYPES = frozenset(
    {
        "array",
        "array[string]",
        "array[number]",
        "array[object]",
        "array[boolean]",
        "array[file]",
        "array[any]",
        "arrayString",
        "arrayNumber",
        "arrayObject",
        "arrayBoolean",
        "arrayFile",
    }
)


_FILE_OUTPUT_TYPES = frozenset({"file", "arrayFile", "array[file]"})


_FILE_SUB_FIELDS = frozenset({"type", "size", "name", "url", "extension", "mime_type", "related_id", "transfer_method"})


_OBJECT_OUTPUT_TYPES = frozenset({"object", "json-object"})


_WORKFLOW_SYS_VARS = frozenset({"files", "user_id", "app_id", "workflow_id", "workflow_run_id", "timestamp"})


_CHAT_SYS_VARS = frozenset(
    {"query", "files", "conversation_id", "user_id", "dialogue_count", "app_id", "workflow_id", "workflow_run_id"}
)


def _is_sys_query_selector(value: Any) -> bool:
    """Recognize the valid selector and common one-item LLM variants."""
    if value == ["sys", "query"]:
        return True
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str):
        return False
    return _is_sys_query_token(value[0])


def _is_sys_query_token(value: str) -> bool:
    """Return whether a string is a compact malformed query selector."""
    return value.replace(" ", "") in {"sys.query", "sys,query"}


def _is_selector_field(key: str) -> bool:
    """Return whether a data field explicitly stores one selector."""
    return key == "selector" or key.endswith("_selector")


def system_variable_names(mode: WorkflowGenerationMode) -> frozenset[str]:
    """System variables the matching app runner actually injects."""
    if mode == "advanced-chat":
        return _CHAT_SYS_VARS
    return _WORKFLOW_SYS_VARS


def _is_selector_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 2 and all(isinstance(item, str) and item for item in value)


def _is_wrapped_single_selector(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 1 and _is_selector_list(value[0])


def _is_multi_wrapped_selectors(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 1 and all(_is_selector_list(item) for item in value)


def _value_mode(parent: dict[str, Any] | None) -> str | None:
    if not isinstance(parent, dict):
        return None
    for key in ("value_type", "input_type"):
        raw = parent.get(key)
        if isinstance(raw, str) and raw in {"variable", "constant", "mixed"}:
            return raw
    raw_type = parent.get("type")
    if isinstance(raw_type, str) and raw_type in {"variable", "constant", "mixed"}:
        return raw_type
    return None


def _field_scan_kind(key: str, parent: dict[str, Any] | None) -> str:
    """How to treat ``parent[key]``: selector, placeholder, or neither."""
    if key in _NON_SELECTOR_LIST_KEYS:
        return "skip"
    mode = _value_mode(parent)
    if key in {"value", "text"} and mode == "constant":
        return "literal"
    if key == "value" and mode == "variable":
        return "selector"
    if key == "query":
        return "query"
    if key == "variables":
        return "selector_list"
    if key in _SELECTOR_KEYS or key.endswith("_selector"):
        return "selector"
    return "walk"


def _selector_tuple(value: list[str]) -> tuple[str, str] | None:
    node_id = value[0].strip()
    var = ".".join(part.strip() for part in value[1:] if part.strip())
    if node_id and var:
        return node_id, var
    return None


def _add_selector_ref(value: Any, out: set[tuple[str, str]]) -> None:
    if _is_selector_list(value):
        ref = _selector_tuple(value)
        if ref is not None:
            out.add(ref)


def _add_placeholders(value: str, out: set[tuple[str, str]]) -> None:
    for match in _VAR_REF_RE.finditer(value):
        node_id, var = match.group(1).strip(), match.group(2).strip()
        if node_id and var:
            out.add((node_id, var))


def _collect_refs_in_data(
    value: Any,
    out: set[tuple[str, str]],
    *,
    parent: dict[str, Any] | None = None,
    key: str = "",
) -> None:
    """Harvest placeholders and typed selectors; ignore constant / schema lists."""
    kind = _field_scan_kind(key, parent) if key else "walk"
    if kind in {"literal", "skip"}:
        if isinstance(value, dict):
            for child_key, item in value.items():
                _collect_refs_in_data(item, out, parent=value, key=child_key)
        return
    if isinstance(value, str):
        _add_placeholders(value, out)
        return
    if kind == "query":
        if _is_multi_wrapped_selectors(value):
            return
        if _is_wrapped_single_selector(value):
            _add_selector_ref(value[0], out)
            return
        _add_selector_ref(value, out)
        if _is_selector_list(value):
            return
    elif kind == "selector":
        _add_selector_ref(value, out)
        if _is_selector_list(value):
            return
    elif kind == "selector_list" and isinstance(value, list):
        for item in value:
            if _is_selector_list(item):
                _add_selector_ref(item, out)
            else:
                _collect_refs_in_data(item, out, parent=parent, key=key)
        return
    if isinstance(value, dict):
        for child_key, item in value.items():
            _collect_refs_in_data(item, out, parent=value, key=child_key)
        return
    if isinstance(value, list):
        for item in value:
            _collect_refs_in_data(item, out, parent=parent, key=key)


def _output_basename(var: str) -> str:
    """Return the declared output name, stripping nested field access."""
    return var.split(".", 1)[0]


def collect_references(data: object) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    _collect_refs_in_data(data, refs)
    return refs


def collect_exact_references(data: object) -> set[tuple[str, ...]]:
    """Collect selectors without collapsing nested path segments.

    Placeholder syntax has no segment-array representation, so its dotted
    variable path is split into the same tuple shape used by runtime selectors.
    """
    refs: set[tuple[str, ...]] = set()

    def add_selector(value: Any) -> None:
        if _is_selector_list(value):
            refs.add(tuple(part.strip() for part in value))

    def walk(value: Any, *, parent: dict[str, Any] | None = None, key: str = "") -> None:
        kind = _field_scan_kind(key, parent) if key else "walk"
        if kind in {"literal", "skip"}:
            if isinstance(value, dict):
                for child_key, item in value.items():
                    walk(item, parent=value, key=child_key)
            return
        if isinstance(value, str):
            refs.update(
                (match.group(1).strip(), *tuple(part.strip() for part in match.group(2).split(".")))
                for match in _VAR_REF_RE.finditer(value)
            )
            return
        if kind == "query":
            if _is_multi_wrapped_selectors(value):
                return
            if _is_wrapped_single_selector(value):
                add_selector(value[0])
                return
            add_selector(value)
            if _is_selector_list(value):
                return
        elif kind == "selector":
            add_selector(value)
            if _is_selector_list(value):
                return
        elif kind == "selector_list" and isinstance(value, list):
            for item in value:
                if _is_selector_list(item):
                    add_selector(item)
                else:
                    walk(item, parent=parent, key=key)
            return
        if isinstance(value, dict):
            for child_key, item in value.items():
                walk(item, parent=value, key=child_key)
        elif isinstance(value, list):
            for item in value:
                walk(item, parent=parent, key=key)

    walk(data)
    return refs
