from types import SimpleNamespace

from graphon.model_runtime.entities.model_entities import ModelFeature
from services.tool_plugin_generator.model_capabilities import ModelCapabilities, from_model_schema


def test_model_capabilities_detect_function_calling_and_json_object():
    schema = SimpleNamespace(
        features=[ModelFeature.TOOL_CALL, ModelFeature.MULTI_TOOL_CALL],
        parameter_rules=[SimpleNamespace(name="response_format", options=["json_object", "text"])],
    )

    capabilities = from_model_schema(schema)

    assert capabilities == ModelCapabilities(
        tool_call=True,
        multi_tool_call=True,
        json_mode=True,
        response_format="json_object",
    )


def test_model_capabilities_does_not_infer_json_mode_from_function_calling():
    schema = SimpleNamespace(features=[ModelFeature.TOOL_CALL], parameter_rules=[])

    capabilities = from_model_schema(schema)

    assert capabilities.tool_call is True
    assert capabilities.multi_tool_call is False
    assert capabilities.json_mode is False
    assert capabilities.response_format is None
