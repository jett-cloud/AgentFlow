---
name: build-container
description: Use when creating, updating, or repairing a Loop or Iteration and its children.
---

# Build container

1. Inspect the container schema and public build_loop/build_iteration arguments.
   For an existing container, read its current graph and child configuration.
   Identify external inputs, child refs, internal dependencies, and public outputs.
   Complete when scope and required execution settings are known.
2. Resolve resource-bearing children with bind-resources. Give ordinary children
   structured intent and exact inputs/output types. Use request-local ref values
   for child edges and selectors; external selectors keep real graph identities.
   Children may use the container's exposed variables in their permitted scope;
   external consumers must use public container outputs, not private child values.
   Complete when all child dependencies and resource bindings are explicit.
3. Supply the whole container: children, internal edges, public outputs, and required
   execution settings. Loop includes initial variables and exit conditions;
   Iteration includes iterator_selector, output_selector, and parallel settings.
   Match branch handles and output aggregation to the schema. The server supplies
   Dify envelopes and system entry-node fields.
   Complete when the payload implements the authorized plan and preserves
   successful children and non-target configuration on edits.
4. Submit build_loop or build_iteration as one atomic mutation. A rejected child
   leaves the previous container unchanged. Use child_ref, path, and available_outputs
   to fix the failed child/field, then resubmit the full container through
   repair-validation; keep successful children in their existing form.
   Complete when the whole container commits and public outputs are confirmed.
5. Return to create-from-scratch or edit-local-node to finish external connections.
   Once construction is complete, activate verify-and-finish.
