"""Full Loop/Iteration submit protocol for the Workflow Assist Agent.

The main Agent describes children by request-local ``ref``, internal edges, and
container-level fields. It must not submit ``parentId``, ``_children``,
``start_node_id``, or synthetic start nodes — Task 5/6 compile those. Nested
containers (child type loop/iteration, or synthetic start) are rejected in v1.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.workflow.generator.compiler.intents.agent_intent import AgentNodeBuildIntent
from core.workflow.generator.compiler.intents.node_intent import NodeBuildIntent, NodeOutputIntent
from core.workflow.generator.compiler.intents.tool_intent import ToolNodeBuildIntent

_NESTED_CONTAINER_TYPES = frozenset({"loop", "iteration", "loop-start", "iteration-start"})
_LOOP_VARIABLE_TYPES = frozenset(
    {
        "string",
        "number",
        "object",
        "boolean",
        "array[string]",
        "array[number]",
        "array[object]",
        "array[boolean]",
    }
)
_ITERATION_ARRAY_TYPES = frozenset(
    {
        "array",
        "arrayString",
        "arrayNumber",
        "arrayBoolean",
        "arrayObject",
        "arrayFile",
        "array[string]",
        "array[number]",
        "array[boolean]",
        "array[object]",
        "array[file]",
    }
)


def _non_empty_ref(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("child ref must be non-empty")
    return normalized


def _selector_parts(value: tuple[str, ...], *, minimum: int) -> tuple[str, ...]:
    if len(value) < minimum:
        raise ValueError("selector requires a node id and output path")
    if any(not item.strip() for item in value):
        raise ValueError("selector parts must be non-empty")
    return tuple(item.strip() for item in value)


class ContainerEdgeIntent(BaseModel):
    source: str
    target: str
    source_handle: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("source", "target")
    @classmethod
    def _non_empty_endpoint(cls, value: str) -> str:
        return _non_empty_ref(value)


class StandardContainerChildIntent(BaseModel):
    kind: Literal["standard"]
    ref: str
    node_type: str
    intent: NodeBuildIntent

    model_config = ConfigDict(extra="forbid")

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _non_empty_ref(value)

    @field_validator("node_type")
    @classmethod
    def _not_nested_container(cls, value: str) -> str:
        node_type = value.strip()
        if not node_type:
            raise ValueError("node_type must be non-empty")
        if node_type in _NESTED_CONTAINER_TYPES:
            raise ValueError("nested containers are not supported")
        return node_type


class ToolContainerChildIntent(BaseModel):
    kind: Literal["tool"]
    ref: str
    intent: ToolNodeBuildIntent

    model_config = ConfigDict(extra="forbid")

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _non_empty_ref(value)


class AgentContainerChildIntent(BaseModel):
    kind: Literal["agent"]
    ref: str
    intent: AgentNodeBuildIntent

    model_config = ConfigDict(extra="forbid")

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _non_empty_ref(value)


ContainerChildIntent = Annotated[
    StandardContainerChildIntent | ToolContainerChildIntent | AgentContainerChildIntent,
    Field(discriminator="kind"),
]


class LoopVariableIntent(BaseModel):
    label: str
    var_type: str
    value_type: Literal["constant", "variable"]
    value: object

    model_config = ConfigDict(extra="forbid")

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        label = value.strip()
        if not label:
            raise ValueError("loop variable label must be non-empty")
        return label

    @field_validator("var_type")
    @classmethod
    def _var_type(cls, value: str) -> str:
        if value not in _LOOP_VARIABLE_TYPES:
            raise ValueError("unsupported loop variable type")
        return value

    @model_validator(mode="after")
    def _initial_value(self) -> Self:
        if self.value_type == "variable":
            if not isinstance(self.value, (list, tuple)) or any(not isinstance(part, str) for part in self.value):
                raise ValueError("variable loop initial value must be a selector")
            self.value = list(_selector_parts(tuple(self.value), minimum=2))
        return self


class LoopBreakConditionIntent(BaseModel):
    id: str
    variable_selector: tuple[str, ...]
    comparison_operator: str
    value: object | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("id", "comparison_operator")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("break condition fields must be non-empty")
        return normalized

    @field_validator("variable_selector")
    @classmethod
    def _selector(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _selector_parts(value, minimum=1)


class LoopBuildIntent(BaseModel):
    loop_count: int
    loop_variables: list[LoopVariableIntent]
    children: list[ContainerChildIntent]
    edges: list[ContainerEdgeIntent] = Field(default_factory=list)
    break_conditions: list[LoopBreakConditionIntent] = Field(default_factory=list)
    outputs: list[NodeOutputIntent] = Field(default_factory=list)
    logical_operator: Literal["and", "or"] = "and"

    model_config = ConfigDict(extra="forbid")

    @field_validator("loop_count", mode="before")
    @classmethod
    def _loop_count(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 100:
            raise ValueError("loop_count must be an integer from 1 to 100")
        return value

    @model_validator(mode="after")
    def _unique_refs_and_edges(self) -> Self:
        _assert_unique_child_refs_and_edges(self.children, self.edges)
        return self


class IterationBuildIntent(BaseModel):
    iterator_selector: tuple[str, ...]
    iterator_input_type: str
    output_selector: tuple[str, ...]
    children: list[ContainerChildIntent]
    edges: list[ContainerEdgeIntent] = Field(default_factory=list)
    outputs: list[NodeOutputIntent] = Field(default_factory=list)
    is_parallel: bool = False
    parallel_nums: int = Field(default=10, ge=1)
    error_handle_mode: str = "terminated"
    flatten_output: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("iterator_selector")
    @classmethod
    def _iterator_selector(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _selector_parts(value, minimum=2)

    @field_validator("output_selector")
    @classmethod
    def _output_selector(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _selector_parts(value, minimum=2)

    @field_validator("iterator_input_type")
    @classmethod
    def _array_input(cls, value: str) -> str:
        if value not in _ITERATION_ARRAY_TYPES:
            raise ValueError("iterator_input_type must be an array type")
        return value

    @model_validator(mode="after")
    def _unique_refs_and_output(self) -> Self:
        refs = _assert_unique_child_refs_and_edges(self.children, self.edges)
        if self.output_selector[0] not in refs:
            raise ValueError("output_selector references unknown child ref")
        return self


def parse_loop_build_intent(raw: object) -> LoopBuildIntent:
    """Parse a complete Loop submit payload. Extra system-owned fields are forbidden."""
    return LoopBuildIntent.model_validate(raw)


def parse_iteration_build_intent(raw: object) -> IterationBuildIntent:
    """Parse a complete Iteration submit payload. Extra system-owned fields are forbidden."""
    return IterationBuildIntent.model_validate(raw)


def _assert_unique_child_refs_and_edges(
    children: list[StandardContainerChildIntent | ToolContainerChildIntent | AgentContainerChildIntent],
    edges: list[ContainerEdgeIntent],
) -> set[str]:
    refs = [child.ref for child in children]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate child ref")
    known = set(refs)
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError("edge references unknown child ref")
    return known
