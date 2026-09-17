---
name: bind-resources
description: Use when discovering or changing Tool, model, dataset, or Agent capability bindings, including exact user references.
---

# Bind resources

1. Read the planned resource role and any existing target configuration.
   referenced_tools and referenced_datasets provide exact identities. Search
   additional tools/datasets only when needed; inspect_tool every chosen Tool,
   even one referenced by exact ID. Use available model catalogue identities.
   Complete when identities and required parameter/output information are known.
   Missing schemas remain unresolved; use recovery or a material user decision
   instead of inventing parameters, outputs, or replacement identities.
2. Record bindings on their consuming plan nodes before mutation.
   A dedicated capability uses build_tool_node. Agent capabilities use
   build_agent_node tools/mcp_tools. Agent-internal knowledge stays in knowledge;
   do not connect a separate retrieval edge for that internal binding.
   A standalone knowledge-retrieval node serves an explicit retrieval graph step.
   Complete when every resource has the intended consumer and the plan accepts it.
3. Encode Tool arguments using the public schema and inspected parameter names.
   Supply required values; omit acceptable defaults. Use kind=constant for literals,
   kind=template for interpolated text, and kind=variable with a full selector for
   variable arguments. File/files parameters require variable selectors, including
   nested paths such as ["iteration_id", "item", "source_image"].
   Do not put `intent.tool.binding` on `build_node`.
   Complete when every required argument is bound with the right representation.
4. For build_agent_node, supply model, instruction, inputs, outputs, and
   tools/mcp_tools/knowledge as top-level arguments. Include the inspected exact
   tool keys required by the instruction. Set knowledge={"operation":"replace",
   "sets":[...]} for the intended complete knowledge set. Omit knowledge on update
   to preserve it; operation=clear requires explicit user removal intent.
   Read before updating and preserve capabilities that remain required.
   Complete when the structured Agent payload expresses every planned capability.
5. Submit through the appropriate builder, or provide the binding to the complete
   container payload. Inspect success and confirmed outputs; route failure through
   repair-validation. Return to the active create/edit/container procedure.
   Complete when the binding is committed; whole-workflow verification belongs to
   verify-and-finish.
