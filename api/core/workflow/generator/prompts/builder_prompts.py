"""Compact semantic configuration references for workflow node builders.

``prompts/nodes.md`` mirrors production ``defaultValue`` from
``web/app/components/workflow/nodes/<type>/default.ts`` so generated graphs
load in Studio identically to a manually-created node.

Snippets are loaded one H2 section at a time (``inspect_node_schema`` and
per-node builders). Do not concatenate the whole file into the live agent
system prompt.
"""

from core.workflow.generator.prompts.loader import read_node_snippet


def get_node_config_snippet(node_type: str) -> str:
    """Return the semantic config reference for one leaf node type."""
    return read_node_snippet(node_type)
