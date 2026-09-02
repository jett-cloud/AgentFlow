---
name: bind-resources
description: Bind the exact tools and knowledge bases listed in CurrentSituation. Use when referenced_tools or referenced_datasets are set.
---

# Bind resources

1. Use the ids in `referenced_tools` and `referenced_datasets` verbatim. Do not call `search_tools`, `search_datasets`, or `ask_user` to pick among them.
2. In the same model reply as any narration, `read_graph` (and `read_node` on the target) before editing.
3. `build_node` for tool / knowledge-retrieval nodes with `purpose` that names those exact ids. The builder writes the binding; do not invent a provider or dataset id.
4. `connect` so retrieval or tool output reaches the next LLM / answer / end node.
5. `validate_graph`, then `finish` when valid. If a listed resource is missing from a tool result, `fail` with that reason — do not substitute another resource.
