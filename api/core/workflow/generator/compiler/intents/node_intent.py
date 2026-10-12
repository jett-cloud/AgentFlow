"""Typed semantic boundary between the Workflow Assist Agent and deterministic compilers.

The main Agent submits node-specific ``structure`` instead of Dify runtime
configuration. Ordinary-node structures are parsed and compiled directly;
specialized Tool, Agent, Loop, and Iteration requests use their own contracts.
"""

import re
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.workflow.generator.compiler.intents.common import ValueIntent
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
    "AssignerStructureIntent",
    "AssignmentIntent",
    "ConstantToolArgument",
    "DocumentExtractorStructureIntent",
    "HttpRequestStructureIntent",
    "HumanInputStructureIntent",
    "IfElseStructureIntent",
    "KnowledgeRetrievalStructureIntent",
    "ListOperatorStructureIntent",
    "NodeBuildIntent",
    "NodeOutputIntent",
    "ParameterExtractorStructureIntent",
    "QuestionClassifierStructureIntent",
    "TemplateToolArgument",
    "ToolArgument",
    "ToolBinding",
    "ToolInvocationIntent",
    "ToolNodeBuildIntent",
    "VariableAggregatorStructureIntent",
    "VariableToolArgument",
    "parse_node_build_intent",
]

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


def _normalize_selector(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(part.strip() for part in value)
    if len(normalized) < 2 or any(not part for part in normalized):
        raise ValueError(f"{label} requires a node id and output path")
    return normalized


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
    type: str | None = None

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
    def _canonical_end_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
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


class DocumentExtractorStructureIntent(BaseModel):
    kind: Literal["document-extractor"]
    source: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(part.strip() for part in value)
        if len(normalized) < 2 or any(not part for part in normalized):
            raise ValueError("document source requires a node id and output path")
        return normalized


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
    operator: str
    value: str | list[str] | bool | int | float | None = None

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


class IfElseCaseIntent(BaseModel):
    id: str
    logical_operator: Literal["and", "or"] = "and"
    conditions: list[ConditionIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("id")
    @classmethod
    def _non_empty_case_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("if-else case id must be non-empty")
        return normalized


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


class QuestionClassIntent(BaseModel):
    id: str
    name: str
    label: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("id", "name")
    @classmethod
    def _non_empty_class_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("class id and name must be non-empty")
        return normalized

    @field_validator("label")
    @classmethod
    def _trim_label(cls, value: str) -> str:
        return value.strip()


class QuestionClassifierStructureIntent(BaseModel):
    kind: Literal["question-classifier"]
    query: tuple[str, ...]
    model: ModelIntent
    classes: list[QuestionClassIntent] = Field(min_length=2)
    instruction: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("query")
    @classmethod
    def _valid_query(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(part.strip() for part in value)
        if len(normalized) < 2 or any(not part for part in normalized):
            raise ValueError("classifier query requires a node id and output path")
        return normalized

    @model_validator(mode="after")
    def _unique_classes(self) -> Self:
        _require_unique([item.id for item in self.classes], "classifier class ids")
        _require_unique([item.name for item in self.classes], "classifier class names")
        return self


_PARAMETER_EXTRACTOR_TYPES = frozenset(
    {
        "string",
        "number",
        "boolean",
        "array[string]",
        "array[number]",
        "array[boolean]",
        "array[object]",
    }
)
_PARAMETER_EXTRACTOR_RESERVED_NAMES = frozenset({"__reason", "__is_success", "__usage"})


class ExtractedParameterIntent(BaseModel):
    name: str
    type: str
    description: str
    required: bool = False
    options: list[str] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _valid_parameter_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("parameter name must be non-empty")
        if normalized in _PARAMETER_EXTRACTOR_RESERVED_NAMES:
            raise ValueError(f"parameter name {normalized!r} is reserved")
        return normalized

    @field_validator("type")
    @classmethod
    def _valid_parameter_type(cls, value: str) -> str:
        normalized = canonical_value_type(value.strip())
        if normalized not in _PARAMETER_EXTRACTOR_TYPES:
            raise ValueError(f"unsupported parameter type {value!r}")
        return normalized

    @field_validator("description")
    @classmethod
    def _non_empty_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("parameter description must be non-empty")
        return normalized

    @field_validator("options")
    @classmethod
    def _valid_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("parameter options must be non-empty")
        _require_unique(normalized, "parameter options")
        return normalized


class ParameterExtractorStructureIntent(BaseModel):
    kind: Literal["parameter-extractor"]
    query: tuple[str, ...]
    model: ModelIntent
    parameters: list[ExtractedParameterIntent] = Field(min_length=1)
    reasoning_mode: Literal["function_call", "prompt"] = "function_call"
    instruction: str = ""

    model_config = ConfigDict(extra="forbid")

    @field_validator("query")
    @classmethod
    def _valid_query(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(part.strip() for part in value)
        if len(normalized) < 2 or any(not part for part in normalized):
            raise ValueError("parameter extractor query requires a node id and output path")
        return normalized

    @model_validator(mode="after")
    def _unique_parameters(self) -> Self:
        _require_unique([item.name for item in self.parameters], "parameter names")
        return self


class VariableAggregatorStructureIntent(BaseModel):
    kind: Literal["variable-aggregator"]
    sources: list[tuple[str, ...]] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("sources")
    @classmethod
    def _valid_sources(cls, value: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
        normalized = [tuple(part.strip() for part in selector) for selector in value]
        if any(len(selector) < 2 or any(not part for part in selector) for selector in normalized):
            raise ValueError("aggregator sources require a node id and output path")
        if len(normalized) != len(set(normalized)):
            raise ValueError("aggregator sources must be unique")
        return normalized


class ListFilterIntent(BaseModel):
    key: str = ""
    operator: str
    value: str | list[str] | bool | int | float | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("key", "operator")
    @classmethod
    def _trim_filter_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _operator_is_present(self) -> Self:
        if not self.operator:
            raise ValueError("filter operator must be non-empty")
        return self


class ListSortIntent(BaseModel):
    key: str
    direction: Literal["asc", "desc"] = "asc"

    model_config = ConfigDict(extra="forbid")

    @field_validator("key")
    @classmethod
    def _non_empty_sort_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("sort key must be non-empty")
        return normalized


class ListOperatorStructureIntent(BaseModel):
    kind: Literal["list-operator"]
    source: tuple[str, ...]
    filters: list[ListFilterIntent] = Field(default_factory=list)
    sort: ListSortIntent | None = None
    limit: int | None = Field(default=None, ge=1, le=1000)
    extract_serial: int | None = Field(default=None, ge=1, le=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(part.strip() for part in value)
        if len(normalized) < 2 or any(not part for part in normalized):
            raise ValueError("list source requires a node id and output path")
        return normalized


class KnowledgeRetrievalStructureIntent(BaseModel):
    kind: Literal["knowledge-retrieval"]
    dataset_ids: list[str] = Field(min_length=1)
    query: tuple[str, ...] | None = None
    attachment: tuple[str, ...] | None = None
    top_k: int = Field(default=4, ge=1, le=10)
    score_threshold: float | None = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("dataset_ids")
    @classmethod
    def _valid_dataset_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("dataset ids must be non-empty")
        _require_unique(normalized, "dataset ids")
        return normalized

    @field_validator("query")
    @classmethod
    def _valid_query(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else _normalize_selector(value, "knowledge query")

    @field_validator("attachment")
    @classmethod
    def _valid_attachment(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else _normalize_selector(value, "knowledge attachment")

    @model_validator(mode="after")
    def _requires_input(self) -> Self:
        if self.query is None and self.attachment is None:
            raise ValueError("knowledge retrieval requires query or attachment")
        return self


_SENSITIVE_HTTP_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "api-key",
        "apikey",
        "api_key",
        "x-api-key",
        "access-token",
        "access_token",
        "secret",
        "token",
    }
)
_SENSITIVE_URL_QUERY_RE = re.compile(
    r"(?:[?&])(?:api[_-]?key|access[_-]?token|secret|token|password)=",
    re.IGNORECASE,
)


class HttpNoAuthIntent(BaseModel):
    kind: Literal["none"] = "none"

    model_config = ConfigDict(extra="forbid")


class HttpCredentialAuthIntent(BaseModel):
    kind: Literal["reference"]
    reference_id: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("reference_id")
    @classmethod
    def _non_empty_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("credential reference id must be non-empty")
        return normalized


HttpAuthorizationIntent = Annotated[HttpNoAuthIntent | HttpCredentialAuthIntent, Field(discriminator="kind")]


class HttpKeyValueIntent(BaseModel):
    name: str
    value: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("HTTP field name must be non-empty")
        if normalized.casefold() in _SENSITIVE_HTTP_NAMES:
            raise ValueError(
                f"HTTP field {normalized!r} may contain credentials; use authorization credential reference"
            )
        if "\n" in normalized or "\r" in normalized or ":" in normalized:
            raise ValueError("HTTP field names must not contain separators or newlines")
        return normalized

    @field_validator("value")
    @classmethod
    def _no_header_injection(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("HTTP field values must not contain newlines")
        return value


class HttpTextFieldIntent(HttpKeyValueIntent):
    kind: Literal["text"] = "text"


class HttpFileFieldIntent(BaseModel):
    kind: Literal["file"] = "file"
    name: str
    source: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        return HttpKeyValueIntent._safe_name(value)

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_selector(value, "HTTP file source")


HttpFormFieldIntent = Annotated[HttpTextFieldIntent | HttpFileFieldIntent, Field(discriminator="kind")]


class HttpNoneBodyIntent(BaseModel):
    kind: Literal["none"] = "none"

    model_config = ConfigDict(extra="forbid")


class HttpTextBodyIntent(BaseModel):
    kind: Literal["raw-text", "json"]
    content: str

    model_config = ConfigDict(extra="forbid")


class HttpFormBodyIntent(BaseModel):
    kind: Literal["form-data", "x-www-form-urlencoded"]
    fields: list[HttpFormFieldIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _urlencoded_is_text_only(self) -> Self:
        if self.kind == "x-www-form-urlencoded" and any(isinstance(item, HttpFileFieldIntent) for item in self.fields):
            raise ValueError("x-www-form-urlencoded body does not support file fields")
        _require_unique([item.name for item in self.fields], "HTTP body field names")
        return self


class HttpBinaryBodyIntent(BaseModel):
    kind: Literal["binary"]
    source: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_selector(value, "HTTP binary source")


HttpBodyIntent = Annotated[
    HttpNoneBodyIntent | HttpTextBodyIntent | HttpFormBodyIntent | HttpBinaryBodyIntent,
    Field(discriminator="kind"),
]


class HttpRequestStructureIntent(BaseModel):
    kind: Literal["http-request"]
    method: Literal["get", "post", "put", "patch", "delete", "head", "options"] = "get"
    url: str
    authorization: HttpAuthorizationIntent = Field(default_factory=HttpNoAuthIntent)
    headers: list[HttpKeyValueIntent] = Field(default_factory=list)
    params: list[HttpKeyValueIntent] = Field(default_factory=list)
    body: HttpBodyIntent = Field(default_factory=HttpNoneBodyIntent)
    ssl_verify: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("url")
    @classmethod
    def _safe_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("HTTP url must be non-empty")
        if _SENSITIVE_URL_QUERY_RE.search(normalized):
            raise ValueError("HTTP url must not contain plaintext credentials")
        return normalized

    @model_validator(mode="after")
    def _unique_fields(self) -> Self:
        _require_unique([item.name.casefold() for item in self.headers], "HTTP header names")
        _require_unique([item.name.casefold() for item in self.params], "HTTP parameter names")
        return self


class HumanConstantStringIntent(BaseModel):
    kind: Literal["constant"]
    value: str = ""

    model_config = ConfigDict(extra="forbid")


class HumanVariableStringIntent(BaseModel):
    kind: Literal["variable"]
    source: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_selector(value, "Human Input default source")


HumanStringSourceIntent = Annotated[
    HumanConstantStringIntent | HumanVariableStringIntent,
    Field(discriminator="kind"),
]


class HumanConstantOptionsIntent(BaseModel):
    kind: Literal["constant"]
    values: list[str] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("values")
    @classmethod
    def _valid_values(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("select options must be non-empty")
        _require_unique(normalized, "select options")
        return normalized


class HumanVariableOptionsIntent(BaseModel):
    kind: Literal["variable"]
    source: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_selector(value, "Human Input options source")


HumanOptionsSourceIntent = Annotated[
    HumanConstantOptionsIntent | HumanVariableOptionsIntent,
    Field(discriminator="kind"),
]


_HUMAN_RESERVED_OUTPUTS = frozenset({"__action_id", "__action_value", "__rendered_content"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _human_output_name(value: str) -> str:
    normalized = value.strip()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError("Human Input output name must be an identifier")
    if normalized in _HUMAN_RESERVED_OUTPUTS:
        raise ValueError(f"Human Input output name {normalized!r} is reserved")
    return normalized


class HumanParagraphInputIntent(BaseModel):
    type: Literal["paragraph"]
    output_variable_name: str
    default: HumanStringSourceIntent | None = None

    model_config = ConfigDict(extra="forbid")

    _valid_name = field_validator("output_variable_name")(_human_output_name)


class HumanSelectInputIntent(BaseModel):
    type: Literal["select"]
    output_variable_name: str
    options: HumanOptionsSourceIntent

    model_config = ConfigDict(extra="forbid")

    _valid_name = field_validator("output_variable_name")(_human_output_name)


class HumanFileInputIntent(BaseModel):
    type: Literal["file", "file-list"]
    output_variable_name: str
    allowed_file_types: list[Literal["document", "image", "audio", "video", "custom"]] = Field(min_length=1)
    allowed_file_upload_methods: list[Literal["local_file", "remote_url"]] = Field(min_length=1)
    allowed_file_extensions: list[str] = Field(default_factory=list)
    number_limits: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")

    _valid_name = field_validator("output_variable_name")(_human_output_name)

    @model_validator(mode="after")
    def _file_requirements(self) -> Self:
        _require_unique(list(self.allowed_file_types), "allowed file types")
        _require_unique(list(self.allowed_file_upload_methods), "allowed upload methods")
        if "custom" in self.allowed_file_types and not self.allowed_file_extensions:
            raise ValueError("custom file inputs require allowed_file_extensions")
        if self.type == "file" and self.number_limits is not None:
            raise ValueError("number_limits is accepted only for file-list")
        return self


HumanFormInputIntent = Annotated[
    HumanParagraphInputIntent | HumanSelectInputIntent | HumanFileInputIntent,
    Field(discriminator="type"),
]


class HumanWebAppDeliveryIntent(BaseModel):
    kind: Literal["webapp"]

    model_config = ConfigDict(extra="forbid")


class HumanEmailDeliveryIntent(BaseModel):
    kind: Literal["email"]
    member_reference_ids: list[str] = Field(min_length=1)
    subject: str
    body: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("member_reference_ids")
    @classmethod
    def _valid_member_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("member reference ids must be non-empty")
        _require_unique(normalized, "member reference ids")
        return normalized

    @field_validator("subject")
    @classmethod
    def _valid_subject(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("email subject must be non-empty")
        return normalized

    @field_validator("body")
    @classmethod
    def _valid_body(cls, value: str) -> str:
        if "{{#url#}}" not in value:
            raise ValueError("email body must include {{#url#}}")
        return value


HumanDeliveryIntent = Annotated[
    HumanWebAppDeliveryIntent | HumanEmailDeliveryIntent,
    Field(discriminator="kind"),
]


class HumanActionIntent(BaseModel):
    id: str = Field(max_length=20, pattern=_IDENTIFIER_RE.pattern)
    title: str = Field(max_length=100)
    button_style: Literal["primary", "default", "accent", "ghost"] = "default"

    model_config = ConfigDict(extra="forbid")

    @field_validator("title")
    @classmethod
    def _non_empty_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Human Input action title must be non-empty")
        return normalized


class HumanInputStructureIntent(BaseModel):
    kind: Literal["human-input"]
    form_content: str
    inputs: list[HumanFormInputIntent] = Field(default_factory=list)
    delivery: list[HumanDeliveryIntent] = Field(min_length=1)
    actions: list[HumanActionIntent] = Field(min_length=1)
    timeout: int | None = Field(default=None, ge=1)
    timeout_unit: Literal["hour", "day"] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("form_content")
    @classmethod
    def _non_empty_form_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Human Input form content must be non-empty")
        return value

    @model_validator(mode="after")
    def _unique_items(self) -> Self:
        _require_unique([item.output_variable_name for item in self.inputs], "Human Input output names")
        _require_unique([item.kind for item in self.delivery], "Human Input delivery methods")
        _require_unique([item.id for item in self.actions], "Human Input action ids")
        return self


class AssignmentIntent(BaseModel):
    """One explicit write to an existing writable workflow variable.

    Phase one intentionally supports only operations whose value contract is
    unambiguous. Additional runtime operations can be added after their type
    matrix is captured in tests.
    """

    target: tuple[str, ...]
    operation: Literal["over-write", "clear"] = "over-write"
    value: ValueIntent | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("target")
    @classmethod
    def _valid_target(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(part.strip() for part in value)
        if len(normalized) < 2 or any(not part for part in normalized):
            raise ValueError("assignment target requires an owner id and variable path")
        return normalized

    @model_validator(mode="after")
    def _operation_value_contract(self) -> Self:
        if self.operation == "clear":
            if self.value is not None:
                raise ValueError("clear must not include value")
        elif self.value is None:
            raise ValueError("over-write requires value")
        return self


class AssignerStructureIntent(BaseModel):
    kind: Literal["assigner"]
    assignments: list[AssignmentIntent] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


NodeStructureIntent = Annotated[
    StartStructureIntent
    | EndStructureIntent
    | AnswerStructureIntent
    | TemplateStructureIntent
    | DocumentExtractorStructureIntent
    | LLMStructureIntent
    | CodeStructureIntent
    | IfElseStructureIntent
    | QuestionClassifierStructureIntent
    | ParameterExtractorStructureIntent
    | VariableAggregatorStructureIntent
    | ListOperatorStructureIntent
    | KnowledgeRetrievalStructureIntent
    | HttpRequestStructureIntent
    | HumanInputStructureIntent
    | AssignerStructureIntent,
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


def _ordinary_intent_json_schema(schema: dict[str, Any]) -> None:
    """Expose only the phase-7 ordinary-node contract to Agent tool schemas."""
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for legacy_name in ("behavior", "inputs", "requirements", "tool", "tool_bindings", "agent_knowledge"):
            properties.pop(legacy_name, None)
    schema["required"] = ["objective", "structure"]


class NodeBuildIntent(BaseModel):
    objective: str
    outputs: list[NodeOutputIntent] = Field(default_factory=list)
    structure: NodeStructureIntent | None = None

    model_config = ConfigDict(extra="forbid", json_schema_extra=_ordinary_intent_json_schema)

    @field_validator("objective")
    @classmethod
    def _non_empty_objective(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("objective must be non-empty")
        return value


def parse_node_build_intent(*, node_type: str, raw: object) -> NodeBuildIntent:
    """Parse intent and enforce the rules that depend on the outer node type."""
    intent = NodeBuildIntent.model_validate(raw)
    if node_type == "code":
        for output in intent.outputs:
            if output.type is None:
                raise ValueError(f"Code output {output.name!r} requires an explicit type")
            if output.type not in _CODE_OUTPUT_TYPES:
                raise ValueError(f"unsupported Code output type {output.type!r}")
    if isinstance(intent.structure, ParameterExtractorStructureIntent) and intent.outputs:
        raise ValueError("Parameter extractor outputs are derived from parameters; omit intent.outputs")
    if (
        isinstance(
            intent.structure,
            KnowledgeRetrievalStructureIntent | HttpRequestStructureIntent | HumanInputStructureIntent,
        )
        and intent.outputs
    ):
        raise ValueError(f"{node_type} outputs are fixed by runtime; omit intent.outputs")
    if intent.structure is not None and intent.structure.kind != node_type:
        raise ValueError(f"intent.structure kind {intent.structure.kind!r} does not match node type {node_type!r}")
    return intent
