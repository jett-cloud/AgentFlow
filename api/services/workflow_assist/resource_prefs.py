"""Prompt helpers that constrain workflow-assist resource selection."""

from __future__ import annotations


def append_soft_resource_preferences(
    instruction: str,
    preferred_tools: list[dict],
    preferred_datasets: list[dict],
) -> str:
    """
    Append optional user preferences without restricting generator choices.

    The planner may omit preferences or request other installed catalogue
    entries; hard authorization happens only during graph generation.
    """
    if not preferred_tools and not preferred_datasets:
        return instruction

    return instruction + (
        "\n\n# User resource preferences (SOFT)\n"
        "Prefer these when relevant; you MAY omit any or add other installed tools/datasets "
        "from the catalogues via resource_requests.\n"
        f"Tools: {_format_tools(preferred_tools)}\n"
        f"Datasets: {_format_datasets(preferred_datasets)}"
    )


def append_authorized_resources(
    instruction: str,
    *,
    approved_tools: list[dict],
    approved_datasets: list[dict],
    preferred_tools: list[dict],
    preferred_datasets: list[dict],
) -> str:
    """
    Append the per-round resource allowlist, combining approved and preferred items.

    An empty union deliberately leaves the instruction unchanged, allowing the
    generator to self-decide from its full installed catalogues.
    """
    tools = _unique_tools([*approved_tools, *preferred_tools])
    datasets = _unique_datasets([*approved_datasets, *preferred_datasets])
    if not tools and not datasets:
        return instruction

    return instruction + (
        "\n\n# Authorized resources for this round\n"
        "For tool and knowledge-retrieval nodes, use ONLY these installed resources (you MAY omit any):\n"
        f"Tools: {_format_tools(tools)}\n"
        f"Datasets: {_format_datasets(datasets)}"
    )


def filter_resource_requests(
    requests: list[dict],
    installed_tool_keys: set[tuple[str, str]],
    installed_dataset_ids: set[str],
) -> list[dict]:
    """Return only well-formed resource requests that exist in tenant catalogues."""
    filtered: list[dict] = []
    for request in requests:
        if request.get("kind") == "tool":
            provider_name = request.get("provider_name")
            tool_name = request.get("tool_name")
            if (
                isinstance(provider_name, str)
                and isinstance(tool_name, str)
                and (provider_name, tool_name) in installed_tool_keys
            ):
                filtered.append(request)
        elif request.get("kind") == "dataset":
            dataset_id = request.get("dataset_id")
            if isinstance(dataset_id, str) and dataset_id in installed_dataset_ids:
                filtered.append(request)
    return filtered


def filter_resource_preferences(
    *,
    preferred_tools: list[dict],
    preferred_datasets: list[dict],
    installed_tool_keys: set[tuple[str, str]],
    installed_dataset_ids: set[str],
) -> tuple[list[dict], list[dict]]:
    """Return preferred tools and datasets that are visible in tenant catalogues."""
    tools = [
        resource
        for resource in preferred_tools
        if isinstance(resource.get("provider_name"), str)
        and isinstance(resource.get("tool_name"), str)
        and (resource["provider_name"], resource["tool_name"]) in installed_tool_keys
    ]
    datasets = [
        resource
        for resource in preferred_datasets
        if isinstance(resource.get("id"), str) and resource["id"] in installed_dataset_ids
    ]
    return tools, datasets


def assert_graph_resources_allowed(
    graph: dict,
    allowed_tool_keys: set[tuple[str, str]],
    allowed_dataset_ids: set[str],
) -> list[dict]:
    """
    Return authorization errors for generated resource nodes.

    An empty allowlist intentionally leaves resource selection unrestricted so
    the generator may self-decide from the tenant's complete catalogue.
    """
    if not allowed_tool_keys and not allowed_dataset_ids:
        return []

    errors: list[dict] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue

        node_id = str(node.get("id", ""))
        if data.get("type") == "tool":
            provider = data.get("provider_name") or data.get("provider_id")
            tool_name = data.get("tool_name")
            if (
                not isinstance(provider, str)
                or not isinstance(tool_name, str)
                or (provider, tool_name) not in allowed_tool_keys
            ):
                errors.append(
                    {
                        "code": "UNAUTHORIZED_RESOURCE",
                        "detail": f"Tool {provider or ''}/{tool_name or ''} is not authorized for this generation.",
                        "node_id": node_id,
                    }
                )
        elif data.get("type") == "knowledge-retrieval":
            dataset_ids = data.get("dataset_ids")
            if not isinstance(dataset_ids, list):
                continue
            for dataset_id in dataset_ids:
                if not isinstance(dataset_id, str) or dataset_id not in allowed_dataset_ids:
                    errors.append(
                        {
                            "code": "UNAUTHORIZED_RESOURCE",
                            "detail": f"Dataset {dataset_id} is not authorized for this generation.",
                            "node_id": node_id,
                        }
                    )
    return errors


def _unique_tools(resources: list[dict]) -> list[dict]:
    unique: dict[tuple[str, str], dict] = {}
    for resource in resources:
        provider_name = resource.get("provider_name")
        tool_name = resource.get("tool_name")
        if isinstance(provider_name, str) and isinstance(tool_name, str):
            unique[(provider_name, tool_name)] = resource
    return [unique[key] for key in sorted(unique)]


def _unique_datasets(resources: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for resource in resources:
        dataset_id = resource.get("id")
        if isinstance(dataset_id, str):
            unique[dataset_id] = resource
    return [unique[key] for key in sorted(unique)]


def _format_tools(resources: list[dict]) -> str:
    names = [f"{resource['provider_name']}/{resource['tool_name']}" for resource in _unique_tools(resources)]
    return ", ".join(names) if names else "None"


def _format_datasets(resources: list[dict]) -> str:
    names = [f'"{resource.get("name", "")}" (id={resource["id"]})' for resource in _unique_datasets(resources)]
    return ", ".join(names) if names else "None"
