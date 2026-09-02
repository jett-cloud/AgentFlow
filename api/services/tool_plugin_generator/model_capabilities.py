"""Model capability detection shared by Agent and scaffold-fill adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.llm_generator.output_parser.structured_output import ResponseFormat
from graphon.model_runtime.entities.model_entities import ModelFeature


@dataclass(frozen=True)
class ModelCapabilities:
    """The provider features that affect tool-plugin generation."""

    tool_call: bool
    multi_tool_call: bool
    json_mode: bool
    response_format: str | None = None


def _value(value: Any) -> str:
    return str(getattr(value, "value", value)).lower()


def from_model_schema(model_schema: Any) -> ModelCapabilities:
    """Build a stable capability contract from a Dify model schema."""
    features = {_value(feature) for feature in (getattr(model_schema, "features", None) or [])}
    tool_call = _value(ModelFeature.TOOL_CALL) in features
    multi_tool_call = _value(ModelFeature.MULTI_TOOL_CALL) in features
    response_format: str | None = None
    raw_rules = getattr(model_schema, "parameter_rules", None)
    if raw_rules is not None and not isinstance(raw_rules, (list, tuple)):
        # Older/custom model adapters may not expose a schema. Keep the legacy
        # JSON-object request in that case; an explicit empty rule list means
        # the provider was inspected and does not support JSON mode.
        return ModelCapabilities(
            tool_call=tool_call,
            multi_tool_call=multi_tool_call,
            json_mode=True,
            response_format="json_object",
        )
    for rule in raw_rules or []:
        if _value(getattr(rule, "name", "")) != "response_format":
            continue
        options = {_value(option) for option in (getattr(rule, "options", None) or [])}
        if _value(ResponseFormat.JSON_OBJECT) in options:
            response_format = ResponseFormat.JSON_OBJECT.value
            break
        if _value(ResponseFormat.JSON) in options:
            response_format = ResponseFormat.JSON.value
            break
    return ModelCapabilities(
        tool_call=tool_call,
        multi_tool_call=multi_tool_call,
        json_mode=response_format is not None,
        response_format=response_format,
    )
