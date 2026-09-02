---
name: edit-local-node
description: Edit one existing node (or a small neighborhood) without rebuilding the workflow. Use when edit_mode is local or a node is selected.
---

# Edit local node

1. Prefer `selected_node` when set. In the same model reply as any narration, `read_node` that id before any `build_node(mode=update)`.
2. `read_graph` only to rewire edges or variable references touching that node.
3. `inspect_node_schema` if the type's legal fields are unclear. Do not recreate unrelated nodes.
4. `build_node(mode=update)` to keep the type; `replace` only when the type must change. Preserve existing edges unless the request is to rewire.
5. `validate_graph`, then `finish` when valid. `ask_user` only if the requested edit is ambiguous about which node or which field.
