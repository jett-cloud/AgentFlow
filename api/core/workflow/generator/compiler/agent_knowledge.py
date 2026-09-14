"""Deterministic Agent v2 knowledge projection helpers.

The Agent node compiler is the only builder that calls ``compile_agent_knowledge``.
Knowledge stays inside Agent V2 ``data.knowledge``; this module never emits a
sibling ``knowledge-retrieval`` node or writes the database.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from core.workflow.generator.compiler.intents.node_intent import AgentKnowledgeIntent

if TYPE_CHECKING:
    from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry


def agent_knowledge_intent_dataset_ids(intent: AgentKnowledgeIntent) -> list[str]:
    """Return unique dataset ids in semantic-intent order."""
    dataset_ids: list[str] = []
    seen: set[str] = set()
    for knowledge_set in intent.sets:
        for dataset_id in knowledge_set.dataset_ids:
            if dataset_id in seen:
                continue
            seen.add(dataset_id)
            dataset_ids.append(dataset_id)
    return dataset_ids


def compile_agent_knowledge(
    intent: AgentKnowledgeIntent,
    catalogue_entries: list[KnowledgeCatalogueEntry],
) -> dict[str, Any]:
    """Compile validated semantic intent into the Agent Soul wire shape."""
    if intent.operation == "clear":
        return {"sets": []}

    entries_by_id = {entry["id"]: entry for entry in catalogue_entries}
    compiled_sets: list[dict[str, Any]] = []
    explicit_names = {knowledge_set.name.casefold() for knowledge_set in intent.sets if knowledge_set.name is not None}
    used_names: set[str] = set()
    for index, knowledge_set in enumerate(intent.sets):
        dataset_ids = sorted(knowledge_set.dataset_ids)
        missing_ids = [dataset_id for dataset_id in dataset_ids if dataset_id not in entries_by_id]
        if missing_ids:
            raise ValueError(f"Unknown Agent knowledge dataset: {missing_ids[0]}")
        if knowledge_set.name is not None:
            set_name = knowledge_set.name
        else:
            default_name = _default_set_name(index=index, dataset_ids=dataset_ids, entries=entries_by_id)
            set_name = _deduplicate_default_set_name(
                default_name,
                unavailable_names=explicit_names | used_names,
            )
        used_names.add(set_name.casefold())
        compiled_sets.append(
            {
                "id": _stable_set_id(name=set_name, dataset_ids=dataset_ids),
                "name": set_name,
                "description": None,
                "datasets": [
                    {
                        "id": dataset_id,
                        "name": entries_by_id[dataset_id]["name"],
                        "description": entries_by_id[dataset_id]["description"],
                    }
                    for dataset_id in dataset_ids
                ],
                "query": {
                    "mode": knowledge_set.query_mode,
                    "value": knowledge_set.query_value,
                },
                "retrieval": {
                    "mode": knowledge_set.retrieval_mode,
                    "top_k": knowledge_set.top_k,
                    "score_threshold": knowledge_set.score_threshold,
                    "reranking_mode": "reranking_model",
                    "reranking_enable": False,
                    "reranking_model": None,
                    "weights": None,
                    "model": None,
                },
                "metadata_filtering": {
                    "mode": "disabled",
                    "model_config": None,
                    "conditions": None,
                },
            }
        )
    return {"sets": compiled_sets}


def apply_agent_knowledge_intent(
    *,
    mode: str,
    config: dict[str, Any],
    old_config: dict[str, Any],
    intent: AgentKnowledgeIntent | None,
    catalogue_entries: list[KnowledgeCatalogueEntry],
) -> None:
    """Discard Builder knowledge and apply explicit or preservation semantics."""
    config.pop("knowledge", None)
    if intent is not None:
        config["knowledge"] = compile_agent_knowledge(intent, catalogue_entries)
        return
    if mode == "update" and isinstance(old_config.get("knowledge"), dict):
        config["knowledge"] = deepcopy(old_config["knowledge"])


def collect_agent_knowledge_dataset_ids(data: dict[str, Any]) -> list[str]:
    """Collect normalized unique ids from `knowledge.sets[].datasets[]`."""
    knowledge = data.get("knowledge")
    if not isinstance(knowledge, dict):
        return []
    raw_sets = knowledge.get("sets")
    if not isinstance(raw_sets, list):
        return []

    dataset_ids: list[str] = []
    seen: set[str] = set()
    for knowledge_set in raw_sets:
        if not isinstance(knowledge_set, dict):
            continue
        datasets = knowledge_set.get("datasets")
        if not isinstance(datasets, list):
            continue
        for dataset in datasets:
            raw_id = dataset.get("id") if isinstance(dataset, dict) else None
            if not isinstance(raw_id, str):
                continue
            dataset_id = raw_id.strip()
            if not dataset_id or dataset_id in seen:
                continue
            seen.add(dataset_id)
            dataset_ids.append(dataset_id)
    return dataset_ids


def _stable_set_id(*, name: str, dataset_ids: list[str]) -> str:
    payload = "\0".join((name.casefold(), *dataset_ids)).encode()
    return f"ks_{hashlib.sha256(payload).hexdigest()[:16]}"


def _default_set_name(
    *,
    index: int,
    dataset_ids: list[str],
    entries: dict[str, KnowledgeCatalogueEntry],
) -> str:
    if len(dataset_ids) == 1:
        name = entries[dataset_ids[0]]["name"].strip()
        if name:
            return name
    return f"Knowledge Set {index + 1}"


def _deduplicate_default_set_name(name: str, *, unavailable_names: set[str]) -> str:
    if name.casefold() not in unavailable_names:
        return name
    suffix = 2
    while f"{name} ({suffix})".casefold() in unavailable_names:
        suffix += 1
    return f"{name} ({suffix})"
