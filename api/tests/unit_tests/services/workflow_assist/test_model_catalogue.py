from types import SimpleNamespace
from unittest.mock import Mock

from services.workflow_assist.model_catalogue import build_agent_model_catalogue


def test_build_agent_model_catalogue_keeps_only_public_identity_fields(monkeypatch) -> None:
    service = Mock()
    service.get_models_by_model_type.return_value = [
        SimpleNamespace(
            provider="langgenius/openai/openai",
            models=[
                SimpleNamespace(
                    model="gpt-4o",
                    model_type=SimpleNamespace(value="llm"),
                    features=[SimpleNamespace(value="vision")],
                    credentials={"api_key": "must-not-leak"},
                )
            ],
        )
    ]
    monkeypatch.setattr("services.workflow_assist.model_catalogue.ModelProviderService", lambda: service)

    result = build_agent_model_catalogue("tenant-1")

    assert result == (
        {
            "provider": "langgenius/openai/openai",
            "name": "gpt-4o",
            "model_type": "llm",
            "features": ("vision",),
        },
    )
    assert "must-not-leak" not in str(result)
    service.get_models_by_model_type.assert_called_once_with(tenant_id="tenant-1", model_type="llm")
