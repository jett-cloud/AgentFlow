"""Shared strict value intents used by deterministic node compilers."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictIntentModel(BaseModel):
    """Base model for model-authored intent; unknown fields are always errors."""

    model_config = ConfigDict(extra="forbid")


class VariableRefIntent(StrictIntentModel):
    """A direct reference to one declared workflow value."""

    kind: Literal["variable"] = "variable"
    selector: tuple[str, ...]

    @field_validator("selector")
    @classmethod
    def _valid_selector(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(part.strip() for part in value)
        if len(normalized) < 2 or any(not part for part in normalized):
            raise ValueError("selector requires a node id and output path")
        return normalized


class ConstantValueIntent(StrictIntentModel):
    """A literal JSON-compatible value."""

    kind: Literal["constant"] = "constant"
    value: Any


ValueIntent = Annotated[VariableRefIntent | ConstantValueIntent, Field(discriminator="kind")]


__all__ = [
    "ConstantValueIntent",
    "StrictIntentModel",
    "ValueIntent",
    "VariableRefIntent",
]
