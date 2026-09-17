"""Compact prompts for parallel, per-node workflow configuration.

Each call produces only the semantic ``data`` fields for one planned node.
Canvas wrappers, shared labels, topology, layout, and edge defaults are owned
by ``WorkflowGenerator`` so completion length scales with node configuration
rather than with the full ReactFlow graph.
"""

import json
from typing import Any

from core.workflow.generator.prompts.builder_prompts import get_node_config_snippet

_NODE_BUILDER_HEAD = """Configure exactly one Dify workflow node.

# Output language

Use the requested language for user-visible content; never translate schema keys,
identifiers, selectors, or literals.

Return only {"config": {...}} with node data. Omit graph/wrapper fields.

Rules:
- Purpose is the spec; preserve its variable references.
- Placeholders use ``{{#node_id.variable#}}``; selectors use ``["node_id", "variable"]``.
- Confirmed outputs exist; provisional ones are same-batch. Never invent IDs.
- Copy the selected model where required.
- Keep prompts/code complete; emit strict JSON.

# Target node schema

"""


NODE_BUILDER_USER_PROMPT = """# Target node

id={node_id}, type={node_type}, label={label!r}
purpose={purpose}

# Output language

{output_language}

# User instruction

{instruction}

{ideal_output_section}{mode_section}{model_section}{tool_catalogue_section}{knowledge_catalogue_section}{start_inputs_section}{existing_config_section}\
# Normalized plan and topology

{plan_json}

Return {{"config": {{...}}}} for target node {node_id} now.
"""


def get_node_builder_system_prompt(node_type: str) -> str:
    """Build a one-node prompt containing only that node's semantic schema."""
    snippet = get_node_config_snippet(node_type)
    return _NODE_BUILDER_HEAD + (snippet or f"- {node_type}: emit the minimum valid config fields.")


def format_parallel_plan(
    plan_nodes: list[dict[str, Any]],
    plan_edges: list[dict[str, Any]],
    start_inputs: list[dict[str, Any]] | None = None,
) -> str:
    """Serialize the shared plan compactly so every node call has graph context.

    ``start_inputs`` rides along so downstream builders reference the declared
    ``{{#<start-id>.<variable>#}}`` names instead of guessing them from prose
    — a guessed name gets auto-injected as a spurious form input later.
    """
    payload: dict[str, Any] = {"nodes": plan_nodes, "edges": plan_edges}
    if start_inputs:
        payload["start_inputs"] = start_inputs
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def format_mode_section(mode: str) -> str:
    """Tell each builder which app mode it is configuring for.

    Matters most in advanced-chat, where ``sys.query`` / ``sys.files`` are the
    sanctioned way to reference the user's message — without this the model
    invents start-node variables that postprocess then materializes as
    spurious form inputs.
    """
    if mode == "advanced-chat":
        return (
            "# App mode\n\n"
            "advanced-chat: the user's chat message is available as sys.query and uploaded files "
            'as sys.files — placeholder {{#sys.query#}}, selector ["sys", "query"]. Reference them '
            "directly; do NOT invent start-node variables for the chat message.\n\n"
        )
    return (
        "# App mode\n\n"
        "workflow: there are NO automatic system variables; reference user input only through "
        "the start node's declared variables.\n\n"
    )


def format_start_inputs_section(start_inputs: list[dict[str, Any]]) -> str:
    """Render planner-declared inputs for the start-node builder only."""
    if not start_inputs:
        return ""
    lines = ["# Start inputs (copy each entry verbatim into start.data.variables)", ""]
    for input_ in start_inputs:
        variable = str(input_.get("variable") or "").strip()
        if not variable:
            continue
        label = str(input_.get("label") or "").strip()
        type_ = str(input_.get("type") or "paragraph").strip()
        lines.append(f"- variable={variable!r}  label={label!r}  type={type_!r}")
    lines.append("")
    return "\n".join(lines) + "\n"


def format_tool_catalogue_section(catalogue_text: str) -> str:
    """Render exact short identifiers for legacy Tool or selected Agent tools."""
    if not catalogue_text.strip():
        return ""
    return (
        "# Available tools (use these exact provider/tool identifiers — "
        "set provider_id and provider_name to the provider portion and "
        "tool_name to the tool portion. For an agent node put the same identifiers "
        "in dify_tools, with provider_type from the catalogue; MCP lines marked "
        "[mcp] may use tool_name=null to select every tool from that server)\n\n"
        f"{catalogue_text}\n\n"
    )


def format_knowledge_catalogue_section(catalogue_text: str) -> str:
    """Render exact dataset IDs for a knowledge-retrieval node builder."""
    if not catalogue_text.strip():
        return ""
    return f"# Available knowledge bases (use only these exact IDs in dataset_ids)\n\n{catalogue_text}\n\n"
