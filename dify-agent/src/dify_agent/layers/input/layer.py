"""Runtime multimodal input layer for Agent vision images.

Maps serializable ``DifyInputLayerConfig`` image DTOs into pydantic-ai
``ImageUrl`` user content so the existing LLM adapter can emit
``ImagePromptMessageContent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar

from pydantic_ai.messages import ImageUrl, UserContent
from typing_extensions import Self, override

from agenton.layers import EmptyRuntimeState, NoLayerDeps, PydanticAILayer
from dify_agent.layers.input.configs import DIFY_INPUT_LAYER_TYPE_ID, DifyInputImageConfig, DifyInputLayerConfig


@dataclass(slots=True)
class DifyInputLayer(PydanticAILayer[NoLayerDeps, object, DifyInputLayerConfig, EmptyRuntimeState]):
    """State-free layer that contributes vision ``ImageUrl`` user prompts."""

    type_id: ClassVar[str | None] = DIFY_INPUT_LAYER_TYPE_ID

    config: DifyInputLayerConfig

    @classmethod
    @override
    def from_config(cls, config: DifyInputLayerConfig) -> Self:
        return cls(config=DifyInputLayerConfig.model_validate(config))

    @property
    @override
    def user_prompts(self) -> list[UserContent]:
        return [_to_image_url(image) for image in self.config.images]


def _to_image_url(image: DifyInputImageConfig) -> ImageUrl:
    identifier = _image_identifier(image.filename)
    return ImageUrl(
        url=image.url,
        media_type=image.mime_type,
        identifier=identifier,
        vendor_metadata={"detail": image.detail},
    )


def _image_identifier(filename: str | None) -> str | None:
    if not filename:
        return None
    stem = PurePosixPath(filename).stem.strip()
    return stem or None


__all__ = ["DifyInputLayer"]
