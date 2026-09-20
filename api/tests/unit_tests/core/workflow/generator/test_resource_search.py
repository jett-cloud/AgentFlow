from core.workflow.generator.resources.knowledge_catalogue import KnowledgeCatalogueEntry
from core.workflow.generator.resources.resource_search import search_knowledge, search_tools
from core.workflow.generator.resources.tool_catalogue import ToolCatalogueEntry


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


def test_tool_search_matches_chinese_display_name_when_catalogue_label_is_english():
    """@图片生成 uses the zh-Hans studio label; catalogue tool_label prefers en_US."""
    entries = [
        _tool(
            "ghy/doubao-image/doubao-image",
            "image_generate",
            "Image Generation",
            "Generate images via Volcengine Ark API.",
        ),
        _tool("time", "current_time", "Current Time", "Return the current time."),
    ]
    entries[0]["search_aliases"] = ("图片生成", "使用豆包(Seedream)模型通过火山引擎Ark API生成图片。")

    results = search_tools(entries, "图片生成")

    assert [(entry["provider_name"], entry["tool_name"]) for entry in results] == [
        ("ghy/doubao-image/doubao-image", "image_generate")
    ]


def test_knowledge_search_uses_name_and_description_across_full_catalogue():
    entries: list[KnowledgeCatalogueEntry] = [
        {"id": f"dataset-{index}", "name": f"Archive {index}", "description": "old records"} for index in range(40)
    ]
    entries.append({"id": "product", "name": "Product Manual", "description": "Current operations guide"})

    results = search_knowledge(entries, "operations guide")

    assert [entry["id"] for entry in results] == ["product"]


def test_knowledge_browse_discovers_file_named_datasets_without_a_keyword():
    entries: list[KnowledgeCatalogueEntry] = [
        {"id": "beads", "name": "拼豆颜色.txt...", "description": "拼豆颜色资料"},
    ]

    assert search_knowledge(entries, "rag 知识库 测试") == []
    assert search_knowledge(entries, "") == entries
    assert search_knowledge(entries, " \t ") == entries


def test_knowledge_browse_is_bounded_stable_and_does_not_reorder_snapshot():
    entries: list[KnowledgeCatalogueEntry] = [
        {"id": f"ds-{index:02d}", "name": f"File {index:02d}", "description": ""}
        for index in reversed(range(20))
    ]

    assert [entry["id"] for entry in search_knowledge(entries, "")] == [f"ds-{index:02d}" for index in range(12)]
    assert entries[0]["id"] == "ds-19"
