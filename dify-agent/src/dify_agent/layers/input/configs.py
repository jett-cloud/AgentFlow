"""Client-safe DTOs for the Dify multimodal input layer.

This layer carries signed image URLs into a run so the model can receive real
vision content. Keep this module free of runtime/pydantic-ai imports so API
request builders can depend on it safely.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agenton.layers import LayerConfig


DIFY_INPUT_LAYER_TYPE_ID: Final[str] = "dify.input"
DEFAULT_VISION_DETAIL: Final[Literal["low", "high"]] = "high"
MAX_VISION_IMAGES: Final[int] = 6


class DifyInputImageConfig(BaseModel):
    """One image attached to the multimodal input layer."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    mime_type: str | None = None
    filename: str | None = None
    detail: Literal["low", "high"] = DEFAULT_VISION_DETAIL

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("image url must not be blank")
        return stripped

    @field_validator("mime_type", "filename")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class DifyInputLayerConfig(LayerConfig):
    """Public config for workflow/agent-app vision image injection."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    images: list[DifyInputImageConfig] = Field(default_factory=list)

    @field_validator("images")
    @classmethod
    def _validate_images(cls, value: list[DifyInputImageConfig]) -> list[DifyInputImageConfig]:
        if len(value) > MAX_VISION_IMAGES:
            raise ValueError(f"images must contain at most {MAX_VISION_IMAGES} item(s)")
        return value


__all__ = [
    "DEFAULT_VISION_DETAIL",
    "DIFY_INPUT_LAYER_TYPE_ID",
    "DifyInputImageConfig",
    "DifyInputLayerConfig",
    "MAX_VISION_IMAGES",
]
