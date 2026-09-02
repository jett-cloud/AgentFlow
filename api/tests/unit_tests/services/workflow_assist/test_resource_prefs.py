from services.workflow_assist.resource_prefs import (
    append_authorized_resources,
    append_soft_resource_preferences,
    assert_graph_resources_allowed,
    filter_resource_preferences,
    filter_resource_requests,
)


def test_append_soft_resource_preferences_includes_requested_resources():
    result = append_soft_resource_preferences(
        "Build a research workflow.",
        preferred_tools=[{"provider_name": "web", "tool_name": "search"}],
        preferred_datasets=[{"id": "dataset-1", "name": "Research"}],
    )

    assert "# User resource preferences (SOFT)" in result
    assert "Tools: web/search" in result
    assert 'Datasets: "Research" (id=dataset-1)' in result


def test_append_soft_resource_preferences_returns_instruction_when_empty():
    instruction = "Build a research workflow."

    assert append_soft_resource_preferences(instruction, [], []) == instruction


def test_append_authorized_resources_returns_instruction_when_all_resources_empty():
    instruction = "Build a research workflow."

    assert (
        append_authorized_resources(
            instruction,
            approved_tools=[],
            approved_datasets=[],
            preferred_tools=[],
            preferred_datasets=[],
        )
        == instruction
    )


def test_append_authorized_resources_unions_approved_and_preferred_resources():
    result = append_authorized_resources(
        "Build a research workflow.",
        approved_tools=[{"provider_name": "web", "tool_name": "search"}],
        approved_datasets=[],
        preferred_tools=[
            {"provider_name": "web", "tool_name": "search"},
            {"provider_name": "math", "tool_name": "sum"},
        ],
        preferred_datasets=[{"id": "dataset-1", "name": "Research"}],
    )

    assert "# Authorized resources for this round" in result
    assert "Tools: math/sum, web/search" in result
    assert 'Datasets: "Research" (id=dataset-1)' in result


def test_append_authorized_resources_treats_preferred_resources_as_authorized():
    result = append_authorized_resources(
        "Build a research workflow.",
        approved_tools=[],
        approved_datasets=[],
        preferred_tools=[{"provider_name": "web", "tool_name": "search"}],
        preferred_datasets=[],
    )

    assert "# Authorized resources for this round" in result
    assert "Tools: web/search" in result


def test_filter_resource_requests_keeps_only_installed_well_formed_resources():
    requests = [
        {"kind": "tool", "provider_name": "web", "tool_name": "search", "reason": "Find sources"},
        {"kind": "tool", "provider_name": "web", "tool_name": "missing", "reason": "Unknown"},
        {"kind": "dataset", "dataset_id": "dataset-1", "dataset_name": "Research", "reason": "Use knowledge"},
        {"kind": "dataset", "dataset_id": "dataset-2", "reason": "Unknown"},
        {"kind": "other", "reason": "Unsupported"},
        {"kind": "tool", "provider_name": "web"},
    ]

    assert filter_resource_requests(
        requests,
        installed_tool_keys={("web", "search")},
        installed_dataset_ids={"dataset-1"},
    ) == [
        {"kind": "tool", "provider_name": "web", "tool_name": "search", "reason": "Find sources"},
        {"kind": "dataset", "dataset_id": "dataset-1", "dataset_name": "Research", "reason": "Use knowledge"},
    ]


def test_filter_resource_preferences_drops_forged_uninstalled_resources():
    tools, datasets = filter_resource_preferences(
        preferred_tools=[
            {"provider_name": "web", "tool_name": "search"},
            {"provider_name": "web", "tool_name": "missing"},
        ],
        preferred_datasets=[
            {"id": "dataset-1", "name": "Research"},
            {"id": "dataset-2", "name": "Forged"},
        ],
        installed_tool_keys={("web", "search")},
        installed_dataset_ids={"dataset-1"},
    )

    assert tools == [{"provider_name": "web", "tool_name": "search"}]
    assert datasets == [{"id": "dataset-1", "name": "Research"}]


def test_assert_graph_resources_allowed_rejects_unauthorized_tool_node():
    errors = assert_graph_resources_allowed(
        {
            "nodes": [
                {
                    "id": "tool-node",
                    "data": {"type": "tool", "provider_id": "web", "tool_name": "browse"},
                }
            ]
        },
        allowed_tool_keys={("web", "search")},
        allowed_dataset_ids=set(),
    )

    assert errors == [
        {
            "code": "UNAUTHORIZED_RESOURCE",
            "detail": "Tool web/browse is not authorized for this generation.",
            "node_id": "tool-node",
        }
    ]


def test_assert_graph_resources_allowed_rejects_unauthorized_dataset_id():
    errors = assert_graph_resources_allowed(
        {
            "nodes": [
                {
                    "id": "knowledge-node",
                    "data": {"type": "knowledge-retrieval", "dataset_ids": ["dataset-1", "dataset-2"]},
                }
            ]
        },
        allowed_tool_keys=set(),
        allowed_dataset_ids={"dataset-1"},
    )

    assert errors == [
        {
            "code": "UNAUTHORIZED_RESOURCE",
            "detail": "Dataset dataset-2 is not authorized for this generation.",
            "node_id": "knowledge-node",
        }
    ]


def test_assert_graph_resources_allowed_does_not_restrict_empty_allowlist():
    assert (
        assert_graph_resources_allowed(
            {
                "nodes": [
                    {
                        "id": "tool-node",
                        "data": {"type": "tool", "provider_name": "web", "tool_name": "browse"},
                    },
                    {
                        "id": "knowledge-node",
                        "data": {"type": "knowledge-retrieval", "dataset_ids": ["dataset-2"]},
                    },
                ]
            },
            allowed_tool_keys=set(),
            allowed_dataset_ids=set(),
        )
        == []
    )
