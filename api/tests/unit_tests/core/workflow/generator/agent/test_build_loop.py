from copy import deepcopy

import pytest

from core.workflow.generator.agent.tools.tool_build_container import compile_build_loop
from core.workflow.generator.agent.tools.tool_results import RETRYABLE_BY_ERROR_CODE, retryable
from core.workflow.generator.agent.tools.tools import TOOL_SCHEMAS, ToolContext, dispatch
from core.workflow.generator.agent.types import ToolCall
from core.workflow.generator.graph.graph_ops import connect, empty_graph, find_node, upsert_node
from core.workflow.generator.types import WorkflowGenerateErrorCode
from tests.unit_tests.core.workflow.generator.agent.conftest import set_env


def _call(**arguments: object) -> ToolCall:
    return {"id": "c1", "name": "build_loop", "arguments": arguments}


def _text_entry() -> dict[str, object]:
    return {
        "provider_name": "text/provider",
        "provider_type": "builtin",
        "plugin_id": "text/provider",
        "tool_name": "summarize",
        "tool_label": "Summarize",
        "description": "Summarize text",
        "parameters": ({"name": "prompt", "type": "string", "form": "llm", "required": True},),
        "parameter_names": ("prompt",),
        "output_names": ("text",),
        "outputs": ({"name": "text", "type": "string"},),
    }


def _typed_entry(output_type: str) -> dict[str, object]:
    entry = _text_entry()
    entry["output_names"] = ("value",)
    entry["outputs"] = ({"name": "value", "type": output_type},)
    return entry


class _BuilderClient:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def iter_json(self, *, messages: object, stage: str):
        del messages, stage
        if False:
            yield ""
        return {"config": self.config}


class _UnexpectedBuilderClient:
    def iter_json(self, *, messages: object, stage: str):
        del messages, stage
        raise AssertionError("fully structured container children must not call Builder")
        yield


def _enable_tools(context: ToolContext) -> None:
    entry = _text_entry()
    set_env(
        context,
        tools_available=True,
        installed_tools={(str(entry["provider_name"]), str(entry["tool_name"]))},
        tool_entries=[entry],
    )


def _outer_graph(*, loop_exists: bool = True, end_reads: str = "acc") -> dict:
    graph = upsert_node(
        empty_graph(),
        node_id="start",
        node_type="start",
        title="开始",
        desc="",
        config={"variables": [{"variable": "query", "label": "Query", "type": "text-input", "required": False}]},
    )
    if loop_exists:
        graph = upsert_node(
            graph,
            node_id="loop1",
            node_type="loop",
            title="累计",
            desc="",
            config={
                "loop_count": 1,
                "logical_operator": "and",
                "loop_variables": [
                    {"id": "old", "label": "old", "var_type": "string", "value_type": "constant", "value": ""}
                ],
            },
        )
        graph = upsert_node(
            graph,
            node_id="loop1_stale",
            node_type="llm",
            title="旧子节点",
            desc="",
            config={"prompt_template": [{"role": "user", "text": "old"}]},
            parent="loop1",
        )
    graph = upsert_node(
        graph,
        node_id="end",
        node_type="end",
        title="结束",
        desc="",
        config={
            "outputs": [
                {
                    "variable": "result",
                    "value_selector": ["loop1", end_reads],
                    "value_type": "string",
                }
            ]
        },
    )
    if loop_exists:
        graph = connect(graph, source="start", target="loop1")
        graph = connect(graph, source="loop1", target="end")
    else:
        graph["edges"] = [
            {"source": "start", "target": "loop1"},
            {"source": "loop1", "target": "end"},
        ]
    return graph


def _fetch_child() -> dict[str, object]:
    return {
        "kind": "tool",
        "ref": "fetch",
        "intent": {
            "binding": {"provider_name": "text/provider", "tool_name": "summarize"},
            "arguments": {"prompt": {"kind": "variable", "selector": ["start", "query"]}},
        },
    }


def _assigner_child(*, source: list[str] | None = None) -> dict[str, object]:
    return {
        "kind": "standard",
        "ref": "write",
        "node_type": "assigner",
        "intent": {
            "objective": "Write the tool result into the loop accumulator",
            "inputs": [{"source": source or ["fetch", "text"], "role": "acc"}],
        },
    }


def _min_loop_args(**changes: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "mode": "update",
        "id": "loop1",
        "title": "累计",
        "loop_count": 10,
        "loop_variables": [{"label": "acc", "var_type": "string", "value_type": "constant", "value": ""}],
        "children": [_fetch_child(), _assigner_child()],
        "edges": [{"source": "fetch", "target": "write"}],
        "break_conditions": [{"id": "c1", "variable_selector": ["acc"], "comparison_operator": "is", "value": "done"}],
        "outputs": [{"name": "acc", "type": "string"}],
        "logical_operator": "and",
    }
    arguments.update(changes)
    return arguments


def test_tool_schemas_contains_build_loop() -> None:
    schema = {item["name"]: dict(item) for item in TOOL_SCHEMAS}["build_loop"]
    parameters = schema["parameters"]
    assert set(parameters["required"]) >= {"mode", "id", "loop_count", "loop_variables", "children"}
    assert parameters["additionalProperties"] is False
    assert "build_loop" in {item["name"] for item in TOOL_SCHEMAS}


def test_build_loop_rejects_runtime_unsafe_id(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph()

    result = dispatch(_call(**_min_loop_args(mode="create", id="loop-2", title="循环")), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_NODE_ID"
    assert find_node(tool_context.state.graph, "loop-2") is None


def test_loop_rejects_names_only_tool_output_when_type_is_required(tool_context: ToolContext) -> None:
    entry = _text_entry()
    entry.pop("outputs")
    entry["output_names"] = ("text",)
    set_env(
        tool_context,
        tools_available=True,
        installed_tools={(str(entry["provider_name"]), str(entry["tool_name"]))},
        tool_entries=[entry],
    )
    tool_context.state.graph = _outer_graph()

    result = dispatch(_call(**_min_loop_args()), tool_context)

    assert result["error_code"] == "TOOL_OUTPUT_SCHEMA_UNAVAILABLE"
    assert tool_context.state.candidate_revision == 0


def test_min_loop_compiles_tool_then_assigner(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph()
    tool_context.state.candidate_revision = 4

    result = dispatch(_call(**_min_loop_args()), tool_context)

    assert result["ok"] is True
    assert result["changed"] is True
    loop = find_node(tool_context.state.graph, "loop1")
    assert loop is not None
    data = loop["data"]
    assert data["start_node_id"] == "loop1start"
    start = find_node(tool_context.state.graph, "loop1start")
    assert start is not None
    assert start.get("parentId") == "loop1"
    assert start["data"]["type"] == "loop-start"
    starts = [node for node in tool_context.state.graph["nodes"] if node["data"].get("type") == "loop-start"]
    assert len(starts) == 1
    fetch = find_node(tool_context.state.graph, "loop1_fetch")
    write = find_node(tool_context.state.graph, "loop1_write")
    assert fetch is not None
    assert fetch.get("parentId") == "loop1"
    assert write is not None
    assert write.get("parentId") == "loop1"
    assert find_node(tool_context.state.graph, "loop1_stale") is None
    edges = {(edge["source"], edge["target"]) for edge in tool_context.state.graph["edges"]}
    assert ("loop1start", "loop1_fetch") in edges
    assert ("loop1_fetch", "loop1_write") in edges
    assert ("start", "loop1") in edges
    assert ("loop1", "end") in edges
    assert any(item.get("label") == "acc" for item in data.get("loop_variables") or [])
    condition = (data.get("break_conditions") or [])[0]
    assert condition["variable_selector"][:2] == ["loop1", "acc"]
    end = find_node(tool_context.state.graph, "end")
    assert end is not None
    assert end["data"]["outputs"][0]["value_selector"] == ["loop1", "acc"]


def test_replace_llm_with_loop_removes_stale_llm_fields(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    graph = _outer_graph()
    node = find_node(graph, "loop1")
    assert node is not None
    node["data"] = {
        "type": "llm",
        "title": "旧模型",
        "desc": "保留描述",
        "model": {"provider": "openai", "name": "gpt-4o"},
        "prompt_template": [{"role": "system", "text": "old"}],
    }
    tool_context.state.graph = graph

    result = dispatch(_call(**_min_loop_args(mode="replace")), tool_context)

    assert result["ok"] is True
    data = find_node(tool_context.state.graph, "loop1")["data"]
    assert data["type"] == "loop"
    assert data["desc"] == "保留描述"
    assert "model" not in data
    assert "prompt_template" not in data


def test_loop_outputs_must_match_loop_variable_labels(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph()

    result = dispatch(_call(**_min_loop_args(outputs=[{"name": "ghost", "type": "string"}])), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_CONTAINER_OUTPUT"


@pytest.mark.parametrize(
    ("output_type", "operator", "value"),
    [("number", ">", "10"), ("boolean", "is", True)],
)
def test_loop_break_condition_uses_resolved_child_output_type(
    tool_context: ToolContext,
    output_type: str,
    operator: str,
    value: object,
) -> None:
    entry = _typed_entry(output_type)
    set_env(
        tool_context,
        tools_available=True,
        installed_tools={(str(entry["provider_name"]), str(entry["tool_name"]))},
        tool_entries=[entry],
    )
    tool_context.state.graph = _outer_graph()
    child = {
        "kind": "tool",
        "ref": "fetch",
        "intent": {
            "binding": {"provider_name": "text/provider", "tool_name": "summarize"},
            "arguments": {"prompt": {"kind": "variable", "selector": ["start", "query"]}},
        },
    }

    result = dispatch(
        _call(
            **_min_loop_args(
                children=[child],
                edges=[],
                break_conditions=[
                    {
                        "id": "c1",
                        "variable_selector": ["fetch", "value"],
                        "comparison_operator": operator,
                        "value": value,
                    }
                ],
            )
        ),
        tool_context,
    )

    assert result["ok"] is True
    condition = find_node(tool_context.state.graph, "loop1")["data"]["break_conditions"][0]
    assert condition["varType"] == output_type


def test_container_if_else_preserves_builder_condition(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    set_env(
        tool_context,
        llm_client=_BuilderClient(
            {
                "cases": [
                    {
                        "case_id": "matched",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": ["start", "query"],
                                "comparison_operator": "contains",
                                "value": "yes",
                                "varType": "string",
                            }
                        ],
                    }
                ]
            }
        ),
    )
    tool_context.state.graph = _outer_graph()
    decision = {
        "kind": "standard",
        "ref": "decision",
        "node_type": "if-else",
        "intent": {
            "objective": "Check whether the user confirmed",
            "inputs": [{"source": ["start", "query"], "role": "condition"}],
        },
    }

    result = dispatch(_call(**_min_loop_args(children=[decision], edges=[])), tool_context)

    assert result["ok"] is True
    node = find_node(tool_context.state.graph, "loop1_decision")
    condition = node["data"]["cases"][0]["conditions"][0]
    assert condition["comparison_operator"] == "contains"
    assert condition["value"] == "yes"


def test_structured_container_child_does_not_call_builder(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    set_env(tool_context, llm_client=_UnexpectedBuilderClient())
    tool_context.state.graph = _outer_graph()
    decision = {
        "kind": "standard",
        "ref": "decision",
        "node_type": "if-else",
        "intent": {
            "objective": "Check whether the user confirmed",
            "inputs": [{"source": ["start", "query"], "role": "condition"}],
            "structure": {
                "kind": "if-else",
                "cases": [
                    {
                        "id": "matched",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "source": ["start", "query"],
                                "type": "string",
                                "operator": "contains",
                                "value": "yes",
                            }
                        ],
                    }
                ],
            },
        },
    }

    result = dispatch(_call(**_min_loop_args(children=[decision], edges=[])), tool_context)

    assert result["ok"] is True, result
    node = find_node(tool_context.state.graph, "loop1_decision")
    condition = node["data"]["cases"][0]["conditions"][0]
    assert condition["variable_selector"] == ["start", "query"]
    assert condition["comparison_operator"] == "contains"


def test_container_standard_child_rejects_builder_that_omits_intent_input(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    set_env(
        tool_context,
        llm_client=_BuilderClient(
            {
                "cases": [
                    {
                        "case_id": "matched",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": ["loop1", "acc"],
                                "comparison_operator": "not empty",
                                "value": None,
                                "varType": "string",
                            }
                        ],
                    }
                ]
            }
        ),
    )
    tool_context.state.graph = _outer_graph()
    original = deepcopy(tool_context.state.graph)
    decision = {
        "kind": "standard",
        "ref": "decision",
        "node_type": "if-else",
        "intent": {
            "objective": "Check whether the user confirmed",
            "inputs": [{"source": ["start", "query"], "role": "condition"}],
        },
    }

    result = dispatch(_call(**_min_loop_args(children=[decision], edges=[])), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "INTENT_INPUT_MISSING"
    assert result["child_ref"] == "decision"
    assert tool_context.state.graph == original


def test_compile_build_loop_does_not_write_the_candidate_graph(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph()
    frozen = tool_context.state.graph
    snapshot = deepcopy(frozen)
    tool_context.state.candidate_revision = 2

    compiled = compile_build_loop(_call(**_min_loop_args()), tool_context)

    assert not isinstance(compiled, dict)
    assert tool_context.state.graph is frozen
    assert tool_context.state.graph == snapshot
    assert tool_context.state.candidate_revision == 2
    assert compiled.compiled.base_revision == 2
    assert compiled.compiled.graph is not frozen


def test_missing_child_tool_output_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph()
    tool_context.state.candidate_revision = 3
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(
        _call(**_min_loop_args(children=[_fetch_child(), _assigner_child(source=["fetch", "missing"])])),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_OUTPUT"
    assert result.get("path")
    assert result.get("child_ref") == "write"
    assert result.get("cause")
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original
    assert tool_context.state.candidate_revision == 3


def test_exit_condition_non_dominated_result_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    set_env(
        tool_context,
        llm_client=_BuilderClient(
            {
                "cases": [
                    {
                        "case_id": "true",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "variable_selector": ["start", "query"],
                                "comparison_operator": "not empty",
                                "value": None,
                                "varType": "string",
                            }
                        ],
                    }
                ]
            }
        ),
    )
    tool_context.state.graph = _outer_graph()
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(
        _call(
            **_min_loop_args(
                children=[
                    {
                        "kind": "standard",
                        "ref": "branch",
                        "node_type": "if-else",
                        "intent": {
                            "objective": "Split on the query",
                            "inputs": [{"source": ["start", "query"], "role": "condition"}],
                        },
                    },
                    _fetch_child(),
                ],
                edges=[
                    {"source": "branch", "target": "fetch", "source_handle": "true"},
                ],
                break_conditions=[
                    {
                        "id": "c1",
                        "variable_selector": ["fetch", "text"],
                        "comparison_operator": "is",
                        "value": "done",
                    }
                ],
            )
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "REFERENCE_NOT_AVAILABLE"
    assert result.get("path")
    assert result.get("cause")
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_broken_internal_cycle_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph()
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(
        _call(
            **_min_loop_args(
                edges=[
                    {"source": "fetch", "target": "write"},
                    {"source": "write", "target": "fetch"},
                ]
            )
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] in {"GRAPH_CYCLE", "INVALID_CONTAINER"}
    assert result.get("path")
    assert result.get("cause")
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_external_output_compatibility_does_not_mutate_graph(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    tool_context.state.graph = _outer_graph(end_reads="acc")
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)

    result = dispatch(
        _call(
            **_min_loop_args(
                loop_variables=[{"label": "other", "var_type": "string", "value_type": "constant", "value": ""}],
                children=[
                    _fetch_child(),
                    {
                        "kind": "standard",
                        "ref": "write",
                        "node_type": "assigner",
                        "intent": {
                            "objective": "Write the tool result into other",
                            "inputs": [{"source": ["fetch", "text"], "role": "other"}],
                        },
                    },
                ],
                outputs=[{"name": "other", "type": "string"}],
            )
        ),
        tool_context,
    )

    assert result["ok"] is False
    assert result["error_code"] == "EXTERNAL_REFERENCE_BROKEN"
    assert result.get("path")
    assert result.get("cause")
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original


def test_external_private_child_ref_is_tool_result_not_keyerror(tool_context: ToolContext) -> None:
    _enable_tools(tool_context)
    graph = _outer_graph()
    end = find_node(graph, "end")
    assert end is not None
    end["data"]["outputs"][0]["value_selector"] = ["loop1_fetch", "text"]
    tool_context.state.graph = graph
    snapshot = tool_context.state.graph
    original = deepcopy(snapshot)
    tool_context.state.candidate_revision = 5

    result = dispatch(_call(**_min_loop_args()), tool_context)

    assert result["ok"] is False
    assert result["error_code"] == "UNRESOLVED_REFERENCE"
    assert result["error_code"] in RETRYABLE_BY_ERROR_CODE
    assert result.get("path")
    assert result.get("child_ref") == "fetch"
    assert result.get("cause")
    assert tool_context.state.graph is snapshot
    assert tool_context.state.graph == original
    assert tool_context.state.candidate_revision == 5


def test_workflow_generate_error_codes_are_registered_retryable() -> None:
    missing = [code.value for code in WorkflowGenerateErrorCode if code.value not in RETRYABLE_BY_ERROR_CODE]
    assert missing == []


def test_retryable_defaults_unknown_codes_to_true() -> None:
    assert retryable("NOT_A_REGISTERED_CODE") is True
