"""Build the credential-free Agent model snapshot for Workflow Assist."""

from operator import itemgetter

from core.workflow.generator.resources.model_catalogue import AgentModelCatalogueEntry
from graphon.model_runtime.entities.model_entities import ModelType
from services.model_provider_service import ModelProviderService


def build_agent_model_catalogue(tenant_id: str) -> tuple[AgentModelCatalogueEntry, ...]:
    """Return active, non-deprecated tenant LLM identities without secrets."""
    providers = ModelProviderService().get_models_by_model_type(
        tenant_id=tenant_id,
        model_type=ModelType.LLM.value,
    )
    entries: list[AgentModelCatalogueEntry] = []
    for provider in providers:
        for model in provider.models:
            entries.append(
                AgentModelCatalogueEntry(
                    provider=provider.provider,
                    name=model.model,
                    model_type=model.model_type.value,
                    features=tuple(feature.value for feature in model.features or ()),
                )
            )
    entries.sort(key=itemgetter("provider", "name"))
    return tuple(entries)
