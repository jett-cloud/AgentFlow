from pydantic_ai.messages import ImageUrl

from dify_agent.layers.input import (
    DIFY_INPUT_LAYER_TYPE_ID,
    DifyInputImageConfig,
    DifyInputLayerConfig,
)
from dify_agent.layers.input.layer import DifyInputLayer


def test_dify_input_layer_type_id_matches_constant() -> None:
    assert DifyInputLayer.type_id == DIFY_INPUT_LAYER_TYPE_ID
    assert DIFY_INPUT_LAYER_TYPE_ID == "dify.input"


def test_dify_input_layer_maps_images_to_image_url_user_prompts() -> None:
    layer = DifyInputLayer.from_config(
        DifyInputLayerConfig(
            images=[
                DifyInputImageConfig(
                    url="https://files.example/signed/swatch.png",
                    mime_type="image/png",
                    filename="swatch.png",
                    detail="high",
                )
            ]
        )
    )

    prompts = layer.user_prompts

    assert len(prompts) == 1
    assert isinstance(prompts[0], ImageUrl)
    assert prompts[0].url == "https://files.example/signed/swatch.png"
    assert prompts[0].media_type == "image/png"
    assert prompts[0].identifier == "swatch"
    assert prompts[0].vendor_metadata == {"detail": "high"}
