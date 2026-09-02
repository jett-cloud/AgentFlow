---
name: create-from-scratch
description: Build a new candidate graph from the user request when the canvas is empty or the user wants a full workflow.
---

# Create from scratch

1. `read_graph` to confirm the candidate is empty or should be rebuilt.
2. In the same model reply, sketch the topology in narration and emit `build_node` tool_calls (`mode=create`). Prefer emitting multiple independent `build_node(mode=create)` tool_calls in one native multi-tool reply so they can compile together. Sequential replies are fine when a later create needs an earlier result. A narration-only reply ends the turn without building. Call `inspect_node_schema` only when the node type's fields are unknown.
3. `connect` nodes in execution order. Use `source_handle` on branching nodes.
4. `validate_graph`. If `valid` is false, follow the repair playbook — do not `finish`.
5. `finish` only after a passing validate on the current revision. Do not `ask_user` about details you can assume; ask only when a decision changes the graph's shape.
