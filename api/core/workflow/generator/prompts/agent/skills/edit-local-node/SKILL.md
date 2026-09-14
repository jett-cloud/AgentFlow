---
name: edit-local-node
description: Use when changing existing nodes or their local connections and downstream bindings.
---

# Edit local node

1. Read read_graph and read_node for the requested targets. Use selected_node and
   referenced_nodes to resolve identity, then confirm type, configuration, existing
   edges, and affected consumers.
   Complete when the requested change and fields to preserve are identified.
2. Submit the edit contract under the system contract gate, using the current base
   hash and requirement evidence. Include allowed nodes and affected downstream
   nodes. Resolve binding changes with bind-resources.
   Complete when the plan authorizes the intended edit without unrelated changes.
3. Route by node type. Ordinary build_node(mode=update) keeps the type; replace is
   for a requested type change. Omitted intent.structure preserves structured
   fields; a supplied structure replaces them, including explicit empty lists.
   Retain required intent inputs/outputs so the call still matches its plan.
   Tool updates require inspected bindings and complete specialized payloads.
   Agent updates follow bind-resources; container edits follow build-container.
   Complete when the target mutation succeeds with the intended retained fields.
4. Update affected selectors and edges if output names/types or topology changed.
   Preserve unrelated nodes and edges. Inspect the resulting graph against the
   edit scope; expand the plan before any necessary additional mutation.
   Complete when affected consumers are reconciled and unrelated state is preserved.
5. Activate verify-and-finish. Use repair-validation first if an edit was rejected.
   Complete this skill when the edited candidate is ready for verification.
