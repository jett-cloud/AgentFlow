from core.workflow.generator.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resource_search import search_knowledge, search_tools
from core.workflow.generator.tool_catalogue import ToolCatalogueEntry


def _tool(provider: str, name: str, label: str, description: str) -> ToolCatalogueEntry:
    return ToolCatalogueEntry(
        provider_name=provider,
        provider_type="builtin",
        plugin_id="",
        tool_name=name,
        tool_label=label,
        description=description,
    )


def test_tool_search_scans_entries_beyond_the_old_eighty_item_cap():
    entries = [_tool("provider", f"tool-{index:03d}", "", "unrelated") for index in range(80)]
    entries.append(_tool("google", "search", "Web Search", "Search the public web."))

    results = search_tools(entries, "web search")

    assert [(entry["provider_name"], entry["tool_name"]) for entry in results] == [("google", "search")]


def test_tool_search_ranks_exact_name_before_description_only_match():
    entries = [
        _tool("misc", "lookup", "Lookup", "Use this for web search."),
        _tool("google", "web_search", "Web Search", "Search pages."),
    ]

    results = search_tools(entries, "web search")

    assert [entry["tool_name"] for entry in results] == ["web_search", "lookup"]


def test_tool_search_has_a_stable_twelve_result_limit():
    entries = [_tool("provider", f"search-{index:02d}", "", "web search") for index in range(20)]

    results = search_tools(entries, "search")

    assert len(results) == 12
    assert [entry["tool_name"] for entry in results] == [f"search-{index:02d}" for index in range(12)]


def test_knowledge_search_uses_name_and_description_across_full_catalogue():
    entries: list[KnowledgeCatalogueEntry] = [
        {"id": f"dataset-{index}", "name": f"Archive {index}", "description": "old records"}
        for index in range(40)
    ]
    entries.append({"id": "product", "name": "Product Manual", "description": "Current operations guide"})

    results = search_knowledge(entries, "operations guide")

    assert [entry["id"] for entry in results] == ["product"]

