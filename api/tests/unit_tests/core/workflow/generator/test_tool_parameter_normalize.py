from copy import deepcopy

import pytest

from core.workflow.generator.compiler.intents.node_intent import ToolInvocationIntent
from core.workflow.generator.compiler.tool_parameter_normalize import (
    ToolNodeConfigError,
    apply_tool_parameter_schema,
    collect_missing_required_tool_parameters,
    compile_tool_node_config,
)
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry
from core.workflow.generator.variables.variable_registry import VariableDeclaration, VariableReferrer, VariableRegistry


def _entry() -> ToolCatalogueEntry:
    return {
        "provider_name": "ghy/doubao-image/doubao-image",
        "provider_type": "builtin",
        "plugin_id": "ghy/doubao-image",
        "tool_name": "image_generate",
        "tool_label": "图片生成",
        "description": "根据提示词和可选参考图生成图片",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": False},
            {
                "name": "size",
                "type": "select",
                "form": "form",
                "required": False,
                "default": "2K",
                "options": ({"value": "1K"}, {"value": "2K"}),
            },
            {"name": "stream", "type": "boolean", "form": "form", "required": False, "default": False},
            {"name": "watermark", "type": "boolean", "form": "form", "required": False, "default": True},
        ),
        "parameter_names": ("prompt", "image", "size", "stream", "watermark"),
        "output_names": ("files",),
    }


def _nodes() -> dict[str, dict[str, object]]:
    return {
        "cutout_loop": {
            "id": "cutout_loop",
            "data": {"type": "start", "variables": [{"variable": "cutout_url", "type": "file"}]},
        },
        "map_agent": {
            "id": "map_agent",
            "data": {
                "type": "code",
                "outputs": {"text": {"type": "string", "children": None}},
            },
        },
    }


def _invocation(arguments: dict[str, object]) -> ToolInvocationIntent:
    return ToolInvocationIntent.model_validate(
        {
            "binding": {
                "provider_name": "ghy/doubao-image/doubao-image",
                "tool_name": "image_generate",
            },
            "arguments": arguments,
        }
    )


def test_compile_tool_node_config_encodes_arguments_and_defaults() -> None:
    config = compile_tool_node_config(
        invocation=_invocation(
            {
                "image": {"kind": "variable", "selector": ["cutout_loop", "cutout_url"]},
                "prompt": {
                    "kind": "template",
                    "text": "根据配色说明生成：{{#map_agent.text#}}",
                },
            }
        ),
        entry=_entry(),
        nodes_by_id=_nodes(),
    )

    assert config == {
        "provider_id": "ghy/doubao-image/doubao-image",
        "provider_name": "ghy/doubao-image/doubao-image",
        "provider_type": "builtin",
        "tool_name": "image_generate",
        "tool_label": "图片生成",
        "tool_node_version": "2",
        "tool_parameters": {
            "image": {"type": "variable", "value": ["cutout_loop", "cutout_url"]},
            "prompt": {"type": "mixed", "value": "根据配色说明生成：{{#map_agent.text#}}"},
            "size": {"type": "constant", "value": "2K"},
            "stream": {"type": "constant", "value": False},
            "watermark": {"type": "constant", "value": True},
        },
        "tool_configurations": {"size": "2K", "stream": False, "watermark": True},
    }


@pytest.mark.parametrize(
    ("explicit", "default", "expected"),
    [
        ([], ["fallback", "items"], []),
        (["only"], ["fallback", "items"], ["only"]),
        (None, [], []),
    ],
)
def test_compile_preserves_short_constant_arrays_and_accepts_empty_array_default(
    explicit: list[str] | None,
    default: list[str],
    expected: list[str],
) -> None:
    entry = _entry()
    entry["parameters"] = (
        *entry["parameters"],
        {"name": "items", "type": "array", "form": "llm", "required": True, "default": default},
    )
    arguments: dict[str, object] = {"prompt": {"kind": "constant", "value": "draw"}}
    if explicit is not None:
        arguments["items"] = {"kind": "constant", "value": explicit}

    config = compile_tool_node_config(
        invocation=_invocation(arguments),
        entry=entry,
        nodes_by_id=_nodes(),
    )

    assert config["tool_parameters"]["items"] == {"type": "constant", "value": expected}


def test_compile_rejects_missing_required_non_file_but_allows_optional_file() -> None:
    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=_invocation({}),
            entry=_entry(),
            nodes_by_id=_nodes(),
        )

    assert exc_info.value.code == "INVALID_NODE_CONFIG"
    assert "prompt" in exc_info.value.detail

    required_file = _entry()
    required_file["parameters"] = (
        {"name": "prompt", "type": "string", "form": "llm", "required": True},
        {"name": "image", "type": "file", "form": "llm", "required": True},
    )
    with pytest.raises(ToolNodeConfigError) as file_exc:
        compile_tool_node_config(
            invocation=_invocation({"prompt": {"kind": "constant", "value": "draw"}}),
            entry=required_file,
            nodes_by_id=_nodes(),
        )
    assert file_exc.value.code == "INVALID_NODE_CONFIG"
    assert "image" in file_exc.value.detail

    entry = _entry()
    entry["parameters"] = tuple(spec for spec in entry["parameters"] if spec["name"] != "prompt")
    config = compile_tool_node_config(invocation=_invocation({}), entry=entry, nodes_by_id=_nodes())
    assert "image" not in config["tool_parameters"]


@pytest.mark.parametrize("argument", [{"kind": "template", "text": "image"}, {"kind": "constant", "value": "x"}])
def test_compile_rejects_non_variable_file_argument(argument: dict[str, object]) -> None:
    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=_invocation(
                {
                    "prompt": {"kind": "constant", "value": "draw"},
                    "image": argument,
                }
            ),
            entry=_entry(),
            nodes_by_id=_nodes(),
        )

    assert exc_info.value.code == "INVALID_NODE_CONFIG"
    assert "variable selector" in exc_info.value.detail


@pytest.mark.parametrize("selector", [["missing", "file"], ["cutout_loop", "missing"]])
def test_compile_rejects_unknown_selector_node_or_output(selector: list[str]) -> None:
    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=_invocation(
                {
                    "prompt": {"kind": "constant", "value": "draw"},
                    "image": {"kind": "variable", "selector": selector},
                }
            ),
            entry=_entry(),
            nodes_by_id=_nodes(),
        )

    assert exc_info.value.code == "UNKNOWN_NODE_REFERENCE"


def _file_registry() -> VariableRegistry:
    return VariableRegistry(
        declarations=(
            VariableDeclaration(
                selector=("start", "image"),
                value_type="file",
                owner_container_id=None,
                producer_layer=0,
                guaranteed=True,
            ),
            VariableDeclaration(
                selector=("start", "images"),
                value_type="array[file]",
                owner_container_id=None,
                producer_layer=0,
                guaranteed=True,
            ),
        ),
        referrers=(VariableReferrer(node_id="tool", layer=1, ancestor_container_ids=()),),
        known_node_ids=frozenset({"start", "tool"}),
    )


def test_compile_uses_variable_registry_for_typed_file_selector() -> None:
    config = compile_tool_node_config(
        invocation=_invocation(
            {
                "prompt": {"kind": "constant", "value": "draw"},
                "image": {"kind": "variable", "selector": ["start", "image"]},
            }
        ),
        entry=_entry(),
        variable_registry=_file_registry(),
        referrer_id="tool",
    )
    assert config["tool_parameters"]["image"] == {"type": "variable", "value": ["start", "image"]}


def test_compile_rejects_array_file_for_file_parameter_via_registry() -> None:
    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=_invocation(
                {
                    "prompt": {"kind": "constant", "value": "draw"},
                    "image": {"kind": "variable", "selector": ["start", "images"]},
                }
            ),
            entry=_entry(),
            variable_registry=_file_registry(),
            referrer_id="tool",
        )
    assert exc_info.value.code == "VARIABLE_TYPE_MISMATCH"


@pytest.mark.parametrize(
    ("parameter_type", "source_type"),
    [("number", "string"), ("boolean", "number"), ("object", "string")],
)
def test_variable_argument_rejects_incompatible_type(parameter_type: str, source_type: str) -> None:
    entry = _entry()
    entry["parameters"] = ({"name": "prompt", "type": parameter_type, "form": "llm", "required": True},)
    registry = VariableRegistry(
        declarations=(
            VariableDeclaration(
                selector=("start", "source"),
                value_type=source_type,
                owner_container_id=None,
                producer_layer=0,
                guaranteed=True,
            ),
        ),
        referrers=(VariableReferrer(node_id="tool", layer=1, ancestor_container_ids=()),),
        known_node_ids=frozenset({"start", "tool"}),
    )

    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=_invocation({"prompt": {"kind": "variable", "selector": ["start", "source"]}}),
            entry=entry,
            variable_registry=registry,
            referrer_id="tool",
        )

    assert exc_info.value.code == "VARIABLE_TYPE_MISMATCH"


def test_compile_accepts_pending_iteration_item_only_for_descendants() -> None:
    pending = {"iteration": {"node_type": "iteration", "outputs": frozenset({"output"})}}
    invocation = _invocation(
        {
            "prompt": {"kind": "constant", "value": "draw"},
            "image": {"kind": "variable", "selector": ["iteration", "item", "source_image"]},
        }
    )

    config = compile_tool_node_config(
        invocation=invocation,
        entry=_entry(),
        nodes_by_id=_nodes(),
        pending_sources=pending,
        referrer_ancestor_ids={"iteration"},
    )
    assert config["tool_parameters"]["image"] == {
        "type": "variable",
        "value": ["iteration", "item", "source_image"],
    }

    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=invocation,
            entry=_entry(),
            nodes_by_id=_nodes(),
            pending_sources=pending,
            referrer_ancestor_ids=set(),
        )
    assert exc_info.value.code == "UNKNOWN_NODE_REFERENCE"


def test_compile_preserves_embedded_string_template_as_mixed() -> None:
    config = compile_tool_node_config(
        invocation=_invocation({"prompt": {"kind": "template", "text": "use {{#map_agent.text#}} as prompt"}}),
        entry=_entry(),
        nodes_by_id=_nodes(),
    )
    assert config["tool_parameters"]["prompt"] == {
        "type": "mixed",
        "value": "use {{#map_agent.text#}} as prompt",
    }


@pytest.mark.parametrize(
    ("arguments", "detail"),
    [
        (
            {"prompt": {"kind": "constant", "value": "draw"}, "size": {"kind": "constant", "value": "8K"}},
            "option",
        ),
        ({"prompt": {"kind": "constant", "value": "draw"}, "bogus": {"kind": "constant", "value": 1}}, "bogus"),
    ],
)
def test_compile_rejects_invalid_select_and_unknown_argument(arguments: dict[str, object], detail: str) -> None:
    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(invocation=_invocation(arguments), entry=_entry(), nodes_by_id=_nodes())
    assert exc_info.value.code == "INVALID_NODE_CONFIG"
    assert detail in exc_info.value.detail


def test_compile_select_accepts_the_exact_declared_option_value_type() -> None:
    entry = _entry()
    entry["parameters"] = (
        *entry["parameters"],
        {
            "name": "quality",
            "type": "select",
            "form": "llm",
            "required": True,
            "options": ({"value": 1}, {"value": 2}),
        },
    )

    config = compile_tool_node_config(
        invocation=_invocation(
            {
                "prompt": {"kind": "constant", "value": "draw"},
                "quality": {"kind": "constant", "value": 1},
            }
        ),
        entry=entry,
        nodes_by_id=_nodes(),
    )

    assert config["tool_parameters"]["quality"] == {"type": "constant", "value": 1}


@pytest.mark.parametrize(
    ("parameter_type", "value"),
    [
        ("checkbox", True),
        ("dynamic-select", 7),
        ("app-selector", "app-id"),
        ("model-selector", []),
    ],
)
def test_compile_rejects_values_outside_dify_parameter_runtime_types(
    parameter_type: str,
    value: object,
) -> None:
    entry = _entry()
    entry["parameters"] = (
        *entry["parameters"],
        {"name": "runtime", "type": parameter_type, "form": "llm", "required": True},
    )

    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(
            invocation=_invocation(
                {
                    "prompt": {"kind": "constant", "value": "draw"},
                    "runtime": {"kind": "constant", "value": value},
                }
            ),
            entry=entry,
            nodes_by_id=_nodes(),
        )

    assert exc_info.value.code == "INVALID_NODE_CONFIG"
    assert parameter_type in exc_info.value.detail


@pytest.mark.parametrize(
    ("parameter_type", "value"),
    [
        ("checkbox", "true"),
        ("dynamic-select", "channel-id"),
        ("app-selector", {"app_id": "app-1"}),
        ("model-selector", {"provider": "openai", "model": "gpt"}),
    ],
)
def test_compile_accepts_values_matching_dify_parameter_runtime_types(
    parameter_type: str,
    value: object,
) -> None:
    entry = _entry()
    entry["parameters"] = (
        *entry["parameters"],
        {"name": "runtime", "type": parameter_type, "form": "llm", "required": True},
    )

    config = compile_tool_node_config(
        invocation=_invocation(
            {
                "prompt": {"kind": "constant", "value": "draw"},
                "runtime": {"kind": "constant", "value": value},
            }
        ),
        entry=entry,
        nodes_by_id=_nodes(),
    )

    assert config["tool_parameters"]["runtime"] == {"type": "constant", "value": value}


def test_compile_rejects_unknown_schema_and_does_not_mutate_inputs() -> None:
    entry = _entry()
    del entry["parameters"]
    invocation = _invocation({"prompt": {"kind": "constant", "value": "draw"}})
    nodes = _nodes()
    snapshots = (deepcopy(entry), invocation.model_copy(deep=True), deepcopy(nodes))

    with pytest.raises(ToolNodeConfigError) as exc_info:
        compile_tool_node_config(invocation=invocation, entry=entry, nodes_by_id=nodes)

    assert exc_info.value.code == "CAPABILITY_UNAVAILABLE"
    assert entry == snapshots[0]
    assert invocation == snapshots[1]
    assert nodes == snapshots[2]


def test_compile_same_binding_update_preserves_trusted_fields_and_overrides_arguments() -> None:
    existing = {
        "provider_id": "ghy/doubao-image/doubao-image",
        "provider_name": "ghy/doubao-image/doubao-image",
        "tool_name": "image_generate",
        "credential_id": "trusted-server-field",
        "tool_parameters": {
            "prompt": {"type": "mixed", "value": "old"},
            "size": {"type": "constant", "value": "1K"},
        },
        "tool_configurations": {"size": "1K"},
    }
    before = deepcopy(existing)

    config = compile_tool_node_config(
        invocation=_invocation({"prompt": {"kind": "constant", "value": "new"}}),
        entry=_entry(),
        nodes_by_id=_nodes(),
        existing_config=existing,
    )

    assert config["credential_id"] == "trusted-server-field"
    assert config["tool_parameters"]["prompt"] == {"type": "constant", "value": "new"}
    assert config["tool_parameters"]["size"] == {"type": "constant", "value": "1K"}
    assert config["tool_configurations"]["size"] == "1K"
    assert existing == before


def test_compile_changed_binding_does_not_inherit_old_parameters_or_credentials() -> None:
    existing = {
        "provider_id": "old",
        "provider_name": "old",
        "tool_name": "old_tool",
        "credential_id": "old-secret-reference",
        "tool_parameters": {"old": {"type": "constant", "value": "x"}},
        "tool_configurations": {"old": "x"},
    }

    config = compile_tool_node_config(
        invocation=_invocation({"prompt": {"kind": "constant", "value": "new"}}),
        entry=_entry(),
        nodes_by_id=_nodes(),
        existing_config=existing,
    )

    assert "credential_id" not in config
    assert "old" not in config["tool_parameters"]
    assert "old" not in config["tool_configurations"]


def test_normalizer_fills_falsy_and_select_defaults_in_both_envelopes() -> None:
    specs = (
        {"name": "disabled", "type": "boolean", "form": "form", "required": False, "default": False},
        {"name": "enabled", "type": "boolean", "form": "form", "required": False, "default": True},
        {"name": "count", "type": "number", "form": "form", "required": False, "default": 0},
        {"name": "size", "type": "select", "form": "form", "required": False, "default": "1024"},
        {"name": "image", "type": "file", "form": "llm", "required": False},
    )
    data: dict[str, object] = {"type": "tool"}

    apply_tool_parameter_schema(data, specs, nodes_by_id={})

    assert data["tool_parameters"] == {
        "disabled": {"type": "constant", "value": False},
        "enabled": {"type": "constant", "value": True},
        "count": {"type": "constant", "value": 0},
        "size": {"type": "constant", "value": "1024"},
    }
    assert data["tool_configurations"] == {
        "disabled": False,
        "enabled": True,
        "count": 0,
        "size": "1024",
    }


def test_normalizer_uses_parameter_schema_before_source_file_type() -> None:
    data = {
        "tool_parameters": {
            "image": {"type": "constant", "value": "start.source_image"},
            "prompt": {"type": "constant", "value": "{{#start.source_image#}}"},
        }
    }
    nodes = _nodes()
    nodes["start"] = {
        "id": "start",
        "data": {"type": "start", "variables": [{"variable": "source_image", "type": "file"}]},
    }

    apply_tool_parameter_schema(
        data,
        (
            {"name": "image", "type": "file", "form": "llm", "required": False},
            {"name": "prompt", "type": "string", "form": "llm", "required": False},
        ),
        nodes_by_id=nodes,
    )

    assert data["tool_parameters"]["image"] == {"type": "variable", "value": ["start", "source_image"]}
    assert data["tool_parameters"]["prompt"] == {
        "type": "mixed",
        "value": "{{#start.source_image#}}",
    }


def test_normalizer_unknown_schema_uses_source_file_type_as_compatibility_fallback() -> None:
    nodes = {
        "start": {
            "id": "start",
            "data": {"type": "start", "variables": [{"variable": "source_image", "type": "file"}]},
        }
    }
    data = {"tool_parameters": {"legacy": "{{#start.source_image#}}"}}

    apply_tool_parameter_schema(data, (), nodes_by_id=nodes)

    assert data["tool_parameters"]["legacy"] == {
        "type": "variable",
        "value": ["start", "source_image"],
    }


def test_normalizer_leaves_contextual_and_invalid_references_unchanged() -> None:
    data = {
        "tool_parameters": {
            "context": {"type": "mixed", "value": "use {{#cutout_loop.cutout_url#}} here"},
            "missing_node": {"type": "constant", "value": "missing.value"},
            "missing_output": {"type": "constant", "value": "cutout_loop.missing"},
        }
    }
    before = deepcopy(data)

    apply_tool_parameter_schema(data, (), nodes_by_id=_nodes())

    assert data["tool_parameters"] == before["tool_parameters"]


def test_normalizer_does_not_replace_present_invalid_parameter_containers() -> None:
    data: dict[str, object] = {"tool_parameters": [], "tool_configurations": "invalid"}

    apply_tool_parameter_schema(data, (), nodes_by_id={})

    assert data == {"tool_parameters": [], "tool_configurations": "invalid"}


def test_normalizer_is_idempotent_and_does_not_invent_optional_file() -> None:
    data = {"tool_parameters": {"prompt": "map_agent.text"}}
    specs = (
        {"name": "prompt", "type": "string", "form": "llm", "required": True},
        {"name": "image", "type": "file", "form": "llm", "required": False},
    )

    apply_tool_parameter_schema(data, specs, nodes_by_id=_nodes())
    once = deepcopy(data)
    apply_tool_parameter_schema(data, specs, nodes_by_id=_nodes())

    assert data == once
    assert data["tool_parameters"]["prompt"] == {"type": "mixed", "value": "{{#map_agent.text#}}"}
    assert "image" not in data["tool_parameters"]


def _missing_param_entry() -> ToolCatalogueEntry:
    return {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "generate",
        "tool_label": "Generate",
        "description": "Generate an image",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "image", "type": "file", "form": "llm", "required": True},
            {"name": "attachments", "type": "files", "form": "llm", "required": True},
            {"name": "optional_image", "type": "file", "form": "llm", "required": False},
        ),
        "parameter_names": ("prompt", "image", "attachments", "optional_image"),
        "output_names": ("files",),
    }


def _missing_param_tool_node(parameters: dict[str, object]) -> dict[str, object]:
    return {
        "id": "tool_1",
        "data": {
            "type": "tool",
            "provider_id": "image/provider",
            "provider_name": "image/provider",
            "tool_name": "generate",
            "tool_parameters": parameters,
        },
    }


def test_collect_missing_required_file_params_same_as_other_required() -> None:
    errors = collect_missing_required_tool_parameters([_missing_param_tool_node({})], [_missing_param_entry()])
    details = [error["detail"] for error in errors]

    assert all(error["code"] == "INVALID_NODE_CONFIG" and error["node_id"] == "tool_1" for error in errors)
    assert any("prompt" in detail for detail in details)
    assert any("image" in detail for detail in details)
    assert any("attachments" in detail for detail in details)
    assert not any("optional_image" in detail for detail in details)


def test_collect_missing_allows_omitted_optional_file_when_required_files_are_bound() -> None:
    errors = collect_missing_required_tool_parameters(
        [
            _missing_param_tool_node(
                {
                    "prompt": {"type": "constant", "value": "draw"},
                    "image": {"type": "variable", "value": ["start", "file"]},
                    "attachments": {"type": "variable", "value": ["start", "files"]},
                }
            )
        ],
        [_missing_param_entry()],
    )

    assert errors == []
