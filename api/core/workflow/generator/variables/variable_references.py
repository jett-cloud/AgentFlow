"""Stable variable reference interface; parsing, declarations and mutation are separate."""

import logging

logger = logging.getLogger(__name__)

from core.workflow.generator.variables.declarations import (
    _declared_output_schema,
    _declared_outputs,
    _declares_variable,
    _element_schema,
    _item_path_allowed,
    _output_path_allowed,
    _schema_allows_path,
    _schema_at_path,
    _schema_for_variable,
    _sole_declared_variable,
    selector_type,
)
from core.workflow.generator.variables.repair import (
    _ensure_llm_context_placeholder,
    _inject_start_variable,
    _insert_multi_retrieval_context_templates,
    _next_generated_node_id,
    _normalize_sys_query_reference_in_data,
    _normalize_sys_query_references,
    _reconcile_variable_references,
    _rewrite_refs_in_data,
    _rewrite_var_ref,
    _rewrite_variable_reference_in_data,
    _sanitize_node_ids,
    _unwrap_single_wrapped_selectors,
)
from core.workflow.generator.variables.syntax import (
    _ARRAY_OUTPUT_TYPES,
    _CHAT_SYS_VARS,
    _CONTAINER_SCOPE_VARS,
    _FILE_OUTPUT_TYPES,
    _FILE_SUB_FIELDS,
    _HITL_BUILTIN_OUTPUTS,
    _ID_FIELDS,
    _INVALID_ID_CHARS_RE,
    _LENIENT_VAR_REF_RE,
    _NON_SELECTOR_LIST_KEYS,
    _OBJECT_OUTPUT_TYPES,
    _PE_BUILTIN_OUTPUTS,
    _SELECTOR_KEYS,
    _VAR_REF_RE,
    _WORKFLOW_SYS_VARS,
    _add_placeholders,
    _add_selector_ref,
    _collect_refs_in_data,
    _field_scan_kind,
    _is_multi_wrapped_selectors,
    _is_selector_field,
    _is_selector_list,
    _is_sys_query_selector,
    _is_sys_query_token,
    _is_wrapped_single_selector,
    _output_basename,
    _selector_tuple,
    _value_mode,
    system_variable_names,
)


class VariableReferences:
    """Compatibility surface for existing callers; rules are implemented in focused modules."""

    _VAR_REF_RE = _VAR_REF_RE
    _LENIENT_VAR_REF_RE = _LENIENT_VAR_REF_RE
    _INVALID_ID_CHARS_RE = _INVALID_ID_CHARS_RE
    _ID_FIELDS = _ID_FIELDS
    _NON_SELECTOR_LIST_KEYS = _NON_SELECTOR_LIST_KEYS
    _SELECTOR_KEYS = _SELECTOR_KEYS
    _CONTAINER_SCOPE_VARS = _CONTAINER_SCOPE_VARS
    _PE_BUILTIN_OUTPUTS = _PE_BUILTIN_OUTPUTS
    _HITL_BUILTIN_OUTPUTS = _HITL_BUILTIN_OUTPUTS
    _ARRAY_OUTPUT_TYPES = _ARRAY_OUTPUT_TYPES
    _FILE_OUTPUT_TYPES = _FILE_OUTPUT_TYPES
    _FILE_SUB_FIELDS = _FILE_SUB_FIELDS
    _OBJECT_OUTPUT_TYPES = _OBJECT_OUTPUT_TYPES
    _WORKFLOW_SYS_VARS = _WORKFLOW_SYS_VARS
    _CHAT_SYS_VARS = _CHAT_SYS_VARS
    _inject_start_variable = staticmethod(_inject_start_variable)
    _normalize_sys_query_references = staticmethod(_normalize_sys_query_references)
    _normalize_sys_query_reference_in_data = staticmethod(_normalize_sys_query_reference_in_data)
    _is_sys_query_selector = staticmethod(_is_sys_query_selector)
    _is_sys_query_token = staticmethod(_is_sys_query_token)
    _is_selector_field = staticmethod(_is_selector_field)
    system_variable_names = staticmethod(system_variable_names)
    _is_selector_list = staticmethod(_is_selector_list)
    selector_type = staticmethod(selector_type)
    _is_wrapped_single_selector = staticmethod(_is_wrapped_single_selector)
    _is_multi_wrapped_selectors = staticmethod(_is_multi_wrapped_selectors)
    _value_mode = staticmethod(_value_mode)
    _field_scan_kind = staticmethod(_field_scan_kind)
    _selector_tuple = staticmethod(_selector_tuple)
    _unwrap_single_wrapped_selectors = staticmethod(_unwrap_single_wrapped_selectors)
    _add_selector_ref = staticmethod(_add_selector_ref)
    _add_placeholders = staticmethod(_add_placeholders)
    _reconcile_variable_references = staticmethod(_reconcile_variable_references)
    _rewrite_variable_reference_in_data = staticmethod(_rewrite_variable_reference_in_data)
    _collect_refs_in_data = staticmethod(_collect_refs_in_data)
    _declared_outputs = staticmethod(_declared_outputs)
    _output_basename = staticmethod(_output_basename)
    _declares_variable = staticmethod(_declares_variable)
    _item_path_allowed = staticmethod(_item_path_allowed)
    _output_path_allowed = staticmethod(_output_path_allowed)
    _schema_for_variable = staticmethod(_schema_for_variable)
    _declared_output_schema = staticmethod(_declared_output_schema)
    _element_schema = staticmethod(_element_schema)
    _schema_at_path = staticmethod(_schema_at_path)
    _schema_allows_path = staticmethod(_schema_allows_path)
    _sole_declared_variable = staticmethod(_sole_declared_variable)
    _sanitize_node_ids = staticmethod(_sanitize_node_ids)
    _rewrite_refs_in_data = staticmethod(_rewrite_refs_in_data)
    _rewrite_var_ref = staticmethod(_rewrite_var_ref)
    _insert_multi_retrieval_context_templates = staticmethod(_insert_multi_retrieval_context_templates)
    _next_generated_node_id = staticmethod(_next_generated_node_id)
    _ensure_llm_context_placeholder = staticmethod(_ensure_llm_context_placeholder)
