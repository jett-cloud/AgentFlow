"""Typed intent boundary between the Workflow Assist Agent and node builders.

The main Agent describes behavior and bindings here; it never submits Dify
node configuration. Tool intents are compiled directly, while non-Tool intents
are rendered into the stable heading format consumed by the existing Builder.
"""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.workflow.generator.compiler.intents.tool_intent import (
    ConstantToolArgument,
    TemplateToolArgument,
    ToolArgument,
    ToolBinding,
    ToolInvocationIntent,
    ToolNodeBuildIntent,
    VariableToolArgument,
)
from core.workflow.generator.variables.variable_types import canonical_value_type

__all__ = [
    "ConstantToolArgument",
    "NodeBuildIntent",
    "NodeInputIntent",
    "NodeOutputIntent",
    "TemplateToolArgument",
    "ToolArgument",
    "ToolBinding",
    "ToolInvocationIntent",
    "ToolNodeBuildIntent",
    "VariableToolArgument",
    "parse_node_build_intent",
    "render_node_builder_spec",
]


_SEMANTIC_COMPLETENESS_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "llm": (
        "prompt_template must contain at least one non-empty message text",
        "model.provider and model.name must be non-empty",
    ),
    "answer": ("answer must be non-empty",),
    "template-transform": (
        "template must be non-empty",
        "variables may be empty; declared variable names must match ^[A-Za-z_][A-Za-z0-9_]*$, "
        "be at most 30 characters, and be unique",
        "each value_selector must contain at least two non-empty strings",
    ),
    "http-request": ("url must be non-empty",),
    "if-else": ("cases and each case's conditions must be non-empty, with valid selectors and values",),
    "question-classifier": (
        "query_variable_selector must be valid, classes must contain at least two unique non-empty ids and names, "
        "and model.provider and model.name must be non-empty",
    ),
    "parameter-extractor": (
        "query must be a valid selector, parameters must contain unique definitions, "
        "and model.provider and model.name must be non-empty",
    ),
    "document-extractor": ("variable_selector must be valid",),
    "variable-aggregator": ("variables must contain valid selectors",),
    "list-operator": ("variable must be a valid selector",),
    "assigner": ("items must contain valid target selectors and operation-aware input values",),
    "human-input": (
        "form_content must be non-empty, delivery_methods must include an enabled method, "
        "and user_actions must not be empty",
    ),
    "iteration": ("iterator_selector and output_selector must be valid",),
}

_INTENT_OUTPUT_TYPES = frozenset(
    {
        "string",
        "number",
        "boolean",
        "object",
        "file",
        "array",
        "array[string]",
        "array[number]",
        "array[boolean]",
        "array[object]",
        "array[file]",
    }
)
_CODE_OUTPUT_TYPES = frozenset(
    {
        "string",
        "number",
        "boolean",
        "object",
        "array[string]",
        "array[number]",
        "array[boolean]",
        "array[object]",
    }
)


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class NodeInputIntent(BaseModel):
    source: tuple[str, ...]
    role: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _non_empty_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2:
            raise ValueError("source requires a node id and output path")
        if any(not item.strip() for item in value):
            raise ValueError("source parts must be non-empty")
        return tuple(item.strip() for item in value)

    @field_validator("role")
    @classmethod
    def _non_empty_role(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("role must be non-empty")
        return value


class NodeOutputFieldIntent(BaseModel):
    type: str
    children: dict[str, "NodeOutputFieldIntent"] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("type")
    @classmethod
    def _supported_type(cls, value: str) -> str:
        normalized = canonical_value_type(value.strip())
        if normalized not in _INTENT_OUTPUT_TYPES:
            raise ValueError(f"unsupported output field type {value!r}")
        return normalized

    @model_validator(mode="after")
    def _children_match_type(self) -> Self:
        if self.children and self.type not in {"object", "array[object]"}:
            raise ValueError("children are supported only for object and array[object] fields")
        return self


class NodeOutputIntent(BaseModel):
    name: str
    type: str | None = None
    children: dict[str, NodeOutputFieldIntent] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("output name must be non-empty")
        return value

    @field_validator("type")
    @classmethod
    def _supported_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = canonical_value_type(value.strip())
        if normalized not in _INTENT_OUTPUT_TYPES:
            raise ValueError(f"unsupported output type {value!r}")
        return normalized

    @model_validator(mode="after")
    def _children_match_type(self) -> Self:
        if self.children and self.type not in {"object", "array[object]"}:
            raise ValueError("children are supported only for object and array[object] outputs")
        return self


class StartVariableIntent(BaseModel):
    name: str
    label: str
    type: Literal["text-input", "paragraph", "select", "number", "file", "file-list", "checkbox", "json_object"]
    required: bool = False
    max_length: int | None = Field(default=None, ge=1)
    options: list[str] = Field(default_factory=list)
    allowed_file_types: list[Literal["document", "image", "audio", "video", "custom"]] = Field(default_factory=list)
    allowed_file_upload_methods: list[Literal["local_file", "remote_url"]] = Field(default_factory=list)
    allowed_file_extensions: list[str] = Field(default_factory=list)
    default: str | float | bool | None = None
    json_schema: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "label")
    @classmethod
    def _non_empty_start_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("start variable name and label must be non-empty")
        return normalized

    @model_validator(mode="after")
    def _type_requirements(self) -> Self:
        if self.type in {"file", "file-list"}:
            if not self.allowed_file_types:
                raise ValueError("file inputs require allowed_file_types")
            if not self.allowed_file_upload_methods:
                raise ValueError("file inputs require allowed_file_upload_methods")
            if "custom" in self.allowed_file_types and not self.allowed_file_extensions:
                raise ValueError("custom file inputs require allowed_file_extensions")
        if self.type == "select" and not self.options:
            raise ValueError("select inputs require options")
        if self.type == "json_object" and self.json_schema is None:
            raise ValueError("json_object inputs require json_schema")
        return self


class StartStructureIntent(BaseModel):
    kind: Literal["start"]
    variables: list[StartVariableIntent]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_variables(self) -> Self:
        _require_unique([item.name for item in self.variables], "start variable names")
        return self


class EndOutputIntent(BaseModel):
    name: str
    source: tuple[str, ...]
    type: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _non_empty_end_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("end output name must be non-empty")
        return normalized

    @field_validator("source")
    @classmethod
    def _valid_end_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2 or any(not item.strip() for item in value):
            raise ValueError("end output source requires a node id and output path")
        return tuple(item.strip() for item in value)

    @field_validator("type")
    @classmethod
    def _canonical_end_type(cls, value: str) -> str:
        normalized = canonical_value_type(value.strip())
        if normalized not in _INTENT_OUTPUT_TYPES | {"any", "array[any]", "integer", "secret"}:
            raise ValueError(f"unsupported end output type {value!r}")
        return normalized


class EndStructureIntent(BaseModel):
    kind: Literal["end"]
    outputs: list[EndOutputIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_outputs(self) -> Self:
        _require_unique([item.name for item in self.outputs], "end output names")
        return self


class AnswerStructureIntent(BaseModel):
    kind: Literal["answer"]
    content: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("content")
    @classmethod
    def _non_empty_answer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer content must be non-empty")
        return value


class NamedBindingIntent(BaseModel):
    name: str
    source: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _valid_binding_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized.replace("_", "a").isalnum() or normalized[0].isdigit():
            raise ValueError("binding name must be an identifier")
        return normalized

    @field_validator("source")
    @classmethod
    def _valid_binding_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2 or any(not item.strip() for item in value):
            raise ValueError("binding source requires a node id and output path")
        return tuple(item.strip() for item in value)


class TemplateStructureIntent(BaseModel):
    kind: Literal["template-transform"]
    template: str
    bindings: list[NamedBindingIntent] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("template")
    @classmethod
    def _non_empty_template(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("template must be non-empty")
        return value

    @model_validator(mode="after")
    def _unique_bindings(self) -> Self:
        _require_unique([item.name for item in self.bindings], "template binding names")
        return self


class ModelIntent(BaseModel):
    provider: str
    name: str
    mode: str = "chat"
    completion_params: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "name", "mode")
    @classmethod
    def _non_empty_model_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model fields must be non-empty")
        return normalized


class PromptMessageIntent(BaseModel):
    role: Literal["system", "user", "assistant"]
    text: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("text")
    @classmethod
    def _non_empty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt text must be non-empty")
        return value


class LLMStructureIntent(BaseModel):
    kind: Literal["llm"]
    model: ModelIntent
    prompt: list[PromptMessageIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class CodeStructureIntent(BaseModel):
    kind: Literal["code"]
    language: Literal["python3", "javascript"] = "python3"
    code: str
    bindings: list[NamedBindingIntent] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("code")
    @classmethod
    def _non_empty_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("code must be non-empty")
        return value

    @model_validator(mode="after")
    def _unique_bindings(self) -> Self:
        _require_unique([item.name for item in self.bindings], "code binding names")
        return self


class ConditionIntent(BaseModel):
    source: tuple[str, ...]
    type: str
    operator: str
    value: str | float | bool | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _valid_condition_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2 or any(not item.strip() for item in value):
            raise ValueError("condition source requires a node id and output path")
        return tuple(item.strip() for item in value)

    @field_validator("operator")
    @classmethod
    def _non_empty_operator(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("condition operator must be non-empty")
        return normalized

    @field_validator("type")
    @classmethod
    def _canonical_condition_type(cls, value: str) -> str:
        normalized = canonical_value_type(value.strip())
        if normalized not in _INTENT_OUTPUT_TYPES:
            raise ValueError(f"unsupported condition type {value!r}")
        return normalized


class IfElseCaseIntent(BaseModel):
    id: str
    logical_operator: Literal["and", "or"] = "and"
    conditions: list[ConditionIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class IfElseStructureIntent(BaseModel):
    kind: Literal["if-else"]
    cases: list[IfElseCaseIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_cases(self) -> Self:
        _require_unique([case.id for case in self.cases], "if-else case ids")
        if any(case.id == "false" for case in self.cases):
            raise ValueError("if-else case id 'false' is reserved for ELSE")
        return self


NodeStructureIntent = Annotated[
    StartStructureIntent
    | EndStructureIntent
    | AnswerStructureIntent
    | TemplateStructureIntent
    | LLMStructureIntent
    | CodeStructureIntent
    | IfElseStructureIntent,
    Field(discriminator="kind"),
]


class AgentKnowledgeSetIntent(BaseModel):
    name: str | None = None
    dataset_ids: list[str]
    query_mode: Literal["generated_query", "user_query"] = "generated_query"
    query_value: str | None = None
    retrieval_mode: Literal["multiple"] = "multiple"
    top_k: int = Field(default=4, ge=1, le=20)
    score_threshold: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _non_empty_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("knowledge set name must be non-empty when provided")
        return normalized

    @field_validator("dataset_ids")
    @classmethod
    def _non_empty_dataset_ids(cls, value: list[str]) -> list[str]:
        normalized = [dataset_id.strip() for dataset_id in value]
        if not normalized or any(not dataset_id for dataset_id in normalized):
            raise ValueError("knowledge set requires at least one dataset id")
        if len(normalized) != len(set(normalized)):
            raise ValueError("knowledge set dataset ids must be unique")
        return normalized

    @model_validator(mode="after")
    def _complete_query(self) -> Self:
        if self.query_mode == "user_query" and not (self.query_value or "").strip():
            raise ValueError("query_value is required for user_query mode")
        if self.query_value is not None:
            self.query_value = self.query_value.strip() or None
        return self


class AgentKnowledgeIntent(BaseModel):
    operation: Literal["replace", "clear"]
    sets: list[AgentKnowledgeSetIntent] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _canonicalize_clear(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("operation") == "clear":
            return {**value, "sets": []}
        return value

    @model_validator(mode="after")
    def _validate_operation(self) -> Self:
        if self.operation == "replace" and not self.sets:
            raise ValueError("replace requires at least one knowledge set")
        names = [knowledge_set.name.casefold() for knowledge_set in self.sets if knowledge_set.name is not None]
        if len(names) != len(set(names)):
            raise ValueError("knowledge set names must be unique")
        return self


class NodeBuildIntent(BaseModel):
    objective: str
    behavior: str = ""
    inputs: list[NodeInputIntent] = Field(default_factory=list)
    outputs: list[NodeOutputIntent] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    tool: ToolInvocationIntent | None = None
    tool_bindings: list[ToolBinding] = Field(default_factory=list)
    agent_knowledge: AgentKnowledgeIntent | None = None
    structure: NodeStructureIntent | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("objective")
    @classmethod
    def _non_empty_objective(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("objective must be non-empty")
        return value

    @model_validator(mode="after")
    def _unique_tool_bindings(self) -> Self:
        keys = [(binding.provider_name, binding.tool_name) for binding in self.tool_bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate exact tool binding")
        return self


def parse_node_build_intent(*, node_type: str, raw: object) -> NodeBuildIntent:
    """Parse intent and enforce the rules that depend on the outer node type."""
    intent = NodeBuildIntent.model_validate(raw)
    if node_type == "tool":
        if intent.tool is None:
            raise ValueError("Tool node requires intent.tool with a complete binding")
        if intent.tool_bindings:
            raise ValueError("Tool node binding belongs in intent.tool, not tool_bindings")
    elif intent.tool is not None:
        raise ValueError("intent.tool is accepted only for tool nodes")
    if node_type != "agent" and intent.tool_bindings:
        raise ValueError("tool_bindings are accepted only for agent nodes")
    if node_type != "agent" and intent.agent_knowledge is not None:
        raise ValueError("agent_knowledge is accepted only for agent nodes")
    if node_type == "code":
        for output in intent.outputs:
            if output.type is None:
                raise ValueError(f"Code output {output.name!r} requires an explicit type")
            if output.type not in _CODE_OUTPUT_TYPES:
                raise ValueError(f"unsupported Code output type {output.type!r}")
    if intent.structure is not None and intent.structure.kind != node_type:
        raise ValueError(f"intent.structure kind {intent.structure.kind!r} does not match node type {node_type!r}")
    return intent


def render_node_builder_spec(intent: NodeBuildIntent, *, node_type: str | None = None) -> str:
    """Render a non-Tool intent into the Builder's stable heading protocol."""
    if intent.tool is not None:
        raise ValueError("Tool intent must be compiled without the Node Builder")
    inputs = [f"- {item.role}: {{{{#{'.'.join(item.source)}#}}}}" for item in intent.inputs]
    outputs = [f"- {item.name}" + (f" ({item.type})" if item.type else "") for item in intent.outputs]
    references = [f"- {{{{#{'.'.join(item.source)}#}}}}" for item in intent.inputs]
    resources = [f"- {binding.provider_name}/{binding.tool_name}" for binding in intent.tool_bindings]
    if intent.agent_knowledge is not None:
        resources.extend(
            f"- dataset:{dataset_id}"
            for knowledge_set in intent.agent_knowledge.sets
            for dataset_id in knowledge_set.dataset_ids
        )
    completeness_constraints: tuple[str, ...] = ()
    type_constraints = _SEMANTIC_COMPLETENESS_CONSTRAINTS.get(node_type or "")
    if type_constraints is not None:
        completeness_constraints = (
            "Runtime schema defaults do not make an empty semantic field complete",
            *type_constraints,
            "Do not invent optional fields that the intent does not request",
        )
    if node_type == "agent":
        completeness_constraints = (
            *completeness_constraints,
            "Do not emit knowledge; the server compiles Agent knowledge deterministically",
        )
    constraints = [f"- {item}" for item in (*intent.requirements, *completeness_constraints)]
    return "\n".join(
        (
            "Objective:",
            intent.objective,
            "Inputs:",
            *(inputs or ["none"]),
            "Outputs:",
            *(outputs or ["none"]),
            "Behavior:",
            intent.behavior or "none",
            "Variable references:",
            *(references or ["none"]),
            "Resource bindings:",
            *(resources or ["none"]),
            "Configuration constraints:",
            *(constraints or ["none"]),
            "Fields to preserve:",
            "none",
        )
    )
