"""Deterministic full-catalogue search used by the planner action loop."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from operator import itemgetter

from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry

_MAX_RESULTS = 12
_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(part for part in _TOKEN_RE.split(normalized) if part)


def _match_rank(query: str, primary_fields: tuple[str, ...], all_fields: tuple[str, ...]) -> int | None:
    normalized_query = _normalize(query)
    if not normalized_query:
        return None
    primary = tuple(_normalize(value) for value in primary_fields if value)
    searchable = " ".join(_normalize(value) for value in all_fields if value)
    tokens = normalized_query.split()
    if normalized_query in primary:
        return 0
    if any(value.startswith(normalized_query) for value in primary):
        return 1
    if all(token in " ".join(primary) for token in tokens):
        return 2
    if normalized_query in searchable:
        return 3
    if all(token in searchable for token in tokens):
        return 4
    return None


def _search[Entry: (ToolCatalogueEntry, KnowledgeCatalogueEntry)](
    entries: list[Entry],
    query: str,
    fields: Callable[[Entry], tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]],
    *,
    limit: int,
) -> list[Entry]:
    ranked: list[tuple[int, tuple[str, ...], Entry]] = []
    for entry in entries:
        primary, all_fields, stable_key = fields(entry)
        rank = _match_rank(query, primary, all_fields)
        if rank is not None:
            ranked.append((rank, stable_key, entry))
    ranked.sort(key=itemgetter(0, 1))
    return [entry for _, _, entry in ranked[:limit]]


def search_tools(
    entries: list[ToolCatalogueEntry], query: str, *, limit: int = _MAX_RESULTS
) -> list[ToolCatalogueEntry]:
    """Return the most relevant installed tools with stable tie-breaking."""
    return _search(
        entries,
        query,
        _tool_search_fields,
        limit=limit,
    )


def _tool_search_fields(
    entry: ToolCatalogueEntry,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Include zh-Hans studio labels so @图片生成 can hit an English tool_name."""
    aliases = entry.get("search_aliases") or ()
    return (
        (entry["tool_name"], entry["tool_label"], *aliases, f"{entry['provider_name']} {entry['tool_name']}"),
        (
            entry["provider_name"],
            entry["plugin_id"],
            entry["tool_name"],
            entry["tool_label"],
            entry["description"],
            entry["provider_type"],
            *aliases,
        ),
        (entry["provider_name"], entry["tool_name"]),
    )


def search_knowledge(
    entries: list[KnowledgeCatalogueEntry], query: str, *, limit: int = _MAX_RESULTS
) -> list[KnowledgeCatalogueEntry]:
    """Return the most relevant tenant datasets with stable tie-breaking."""
    return _search(
        entries,
        query,
        lambda entry: (
            (entry["name"],),
            (entry["name"], entry["description"]),
            (entry["name"], entry["id"]),
        ),
        limit=limit,
    )
