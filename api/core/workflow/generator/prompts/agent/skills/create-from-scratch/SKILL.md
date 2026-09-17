---
name: create-from-scratch
description: Use when creating a workflow from an empty candidate or an explicitly requested rebuild.
---

# Create from scratch

1. Read read_graph and the user turns. Identify required steps, final outputs, app
   mode, and assumptions. An existing graph needs explicit rebuild intent.
   Complete when the requested result and rebuild scope are accounted for.
2. Prepare the whole workflow plan under the system contract gate. Resolve resource
   bindings with bind-resources and containers with build-container as needed.
   Submit requirement evidence, node intents, edges/handles, and final outputs.
   Complete when submit_workflow_plan succeeds and the next nodes are resolved.
3. Build using the system builder router and dependency rules. Ordinary nodes use
   build_node(mode=create); supply matching intent.structure for supported types.
   Use inspect_node_schema when fields are unclear. Declare dynamic output types
   explicitly and retain full nested selectors. Constants need no invented input.
   Independent creates may share a native multi-tool batch; consumers that need
   observed results follow in the next invocation.
   Complete when successful results account for every planned node and output;
   recover rejected or dropped calls before counting them as built.
4. Connect the planned control edges, including branch handles. Container internal
   edges belong to the container payload. Compare the resulting read_graph with
   the plan's nodes, edges, outputs, and scopes.
   Complete when all intended construction is committed.
5. Activate verify-and-finish to check and finish the candidate. If construction
   failed, activate repair-validation with the relevant construction skills first.
   Complete this skill when construction is ready for verification; a narration
   of the plan or an uncommitted tool call is not a built graph.
