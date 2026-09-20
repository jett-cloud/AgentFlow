# Workflow Generator Agent Guide (`api/core/workflow/generator`)

## 1. Overview & Architecture Boundaries

This package is the **pure domain logic engine** for generating, refining, and conversational-editing Dify workflow graphs (both standard `workflow` and `advanced-chat` modes).

### Clean Architecture Boundaries (MUST FOLLOW)

```
[Controllers] ──> [Services Layer] ──> [core/workflow/generator (Domain Layer)]
                     │ (DB, Celery, Models)            │ (Pure in-memory domain logic)
                     └────── Dependency Injection ────┘
```

- **NO Infrastructure Imports**: Code in this directory **MUST NOT** import from `services.*`, `models.*` (SQLAlchemy models), `controllers.*`, or use database sessions directly.
- **Dependency Injection**: Model instances, tenant tool/knowledge catalogues, acceptance runners, and hydration callbacks are injected via parameters or typed environment contexts (`ToolEnv`, `BuilderInput`, `PlannerInput`).
- **In-Memory State**: All candidate graph modifications, revisions, and message logs live strictly in-memory during generation. Persistence to PostgreSQL and SSE streaming are handled upstream by `services/workflow_assist/` and `services/workflow_generator_service.py`.

---

## 2. Dual Generation Engines

The package hosts two distinct generation modalities that share underlying layout, builder, and validation components:

| Feature | Pipeline Engine (`pipeline/runner.py`) | Workflow Assist Agent (`agent/`) |
| :--- | :--- | :--- |
| **Invocation Entry** | `WorkflowGenerator.generate_workflow_graph[_stream]` | `agent.loop.iter_agent_events` |
| **Use Case** | Cmd+K `/create` (scratch) & `/refine` (draft update) | Interactive canvas sidebar assistant (chat) |
| **Pattern** | 3-stage deterministic pipeline (Planner ➔ Builders ➔ Postprocessor) | Multi-turn ReAct autonomous agent with specialized build tools |
| **Concurrency** | ThreadPool for parallel node building | ThreadPool for parallel create compilation; serial commit |
| **Correction** | Single-pass validation failure return | Iterative error-observation and self-correction |

---

## 3. Directory & Module Map

```
generator/
├── pipeline/        # Planner state, actions, and legacy pipeline orchestration
├── agent/
│   ├── loop.py      # Turn orchestration and terminal convergence
│   ├── tools/       # Tool schemas, dispatch, mutation, and lifecycle
│   ├── protocol/    # Streaming and tool-call parsing
│   ├── scheduling/  # Parallel compilation; ordered serial commits
│   └── state/       # Tool results, revisions, and append-only messages
├── compiler/        # Ordinary, Agent, tool, and container compilation
│   └── intents/     # Typed build requests and intent contracts
├── validation/      # Topology, containers, resources, branches, and node config
├── variables/       # Selector syntax, declarations, availability, and repair
├── graph/           # Graph types, immutable operations, layout, and IDs
├── contracts/       # Requirement contract, reconciliation, and evidence
├── acceptance/      # Acceptance evidence and graph-bound live trial requests
├── resources/       # Pure catalogue values, formatting, and search
├── model_io/        # Model response parsing and shared logical-call budgets
└── prompts/         # Model prompts and generation skills
```

Tenant database, plugin, and MCP inventory loading belongs to
`services/workflow_assist/{knowledge,tool}_catalogue_loader.py`.
Runtime adapters live outside the generator in `core/workflow/runtime/adapters/`.


---

## 4. Non-Negotiable Invariants (状态机铁律)

When modifying or optimizing `agent/loop.py` and surrounding tools, you **MUST NEVER violate** the following invariants:

### 1. Terminal Convergence Invariant (终态收敛铁律)
- `finish.ok == True` is the **ONLY** path that yields `("done", ...)`.
- `ask_user.ok == True` is the **ONLY** path that yields `("waiting_user", ...)`.
- `fail.ok == True` is the **ONLY** path that yields `("failed", ...)`.
- Natural language narration like *"I have created your workflow"* without calling `finish` **MUST NEVER** end the run as completed; it yields `turn_complete` (waiting for user input).
- `finish` must strictly require: (1) Graph validation passes (`valid=True`), (2) Candidate revision aligns with last validation revision, (3) Sandbox acceptance evidence passes if an acceptance runner is present.

### 2. Revision Monotonicity Invariant (版本单调递增铁律)
- Whenever a tool mutates the candidate graph (`result["changed"] == True`), `session.candidate_revision` must increment by exactly 1 (`session.candidate_revision += 1`).
- Special cases: `finish` and `run_acceptance` run graph hydration and auto-layout internally; they synchronize `context.state.candidate_revision` directly without adding another +1.
- Never reset, decrement, or skip revision numbers.

### 3. Append-Only Message Sequence Invariant (消息只增不改铁律)
- `session.messages` is strictly append-only. Each message receives `sequence = session.messages[-1].sequence + 1`.
- Never mutate, delete, or re-order past messages in `session.messages` in-memory. Compaction works by recording watermarks (`compacted_until_sequence`), not by deleting historical message objects.

### 4. Parallel Compile, Sequential Commit Invariant (并发编译，串行提交)
- When multiple create-mode specialized build tools arrive in a single model turn (`build_node`, `build_tool_node`, `build_agent_node`, `build_loop`, `build_iteration`):
  1. Compiling configurations runs concurrently in worker threads (`ThreadPoolExecutor`).
  2. Committing to the candidate graph runs strictly sequentially in the caller thread in original call order.
- Never write to `context.state.graph` from inside background worker threads.
- Compilers are side-effect-free. Only commit writes `context.state.graph`.
- If an earlier call returns a retryable failure, already-completed results for its
  later siblings are discarded without a commit, tool-result message, or revision bump.

---

## 4b. Specialized public build tools

Five public mutation tools share compile-then-commit:

| Tool | Responsibility | Commit unit |
| :--- | :--- | :--- |
| `build_node` | Ordinary non-tool, non-agent, non-container nodes | One node |
| `build_tool_node` | Installed Tool binding and typed arguments | One node |
| `build_agent_node` | Agent V2 model, tools, MCP, knowledge, IO | One node |
| `build_loop` | Loop config, descendants, internal edges, loop variables, exit, public outputs | Whole container replace |
| `build_iteration` | Iteration config, descendants, item/index scope, aggregated output | Whole container replace |

Shared compilers (`compile_standard_node` / `compile_tool_node` / `compile_agent_node` / `compile_container_subgraph`) must not import `services.*` or `models.*`. `build_loop` / `build_iteration` do not call the public `build_node` tool.

Atomic replace: a container either commits one new subgraph or leaves the previous graph and revision unchanged.

All five public builders reject node IDs outside `[A-Za-z0-9_]+` before lookup or
compilation. Postprocessor ID sanitization is only a defensive compatibility path
for imported graphs; it is not part of the Agent mutation protocol.

Retry classification:
- Mechanical: Builder protocol / completeness, at most 2 attempts inside `container_compiler`. Does not wake the main agent again.
- Semantic: `UNKNOWN_TOOL_OUTPUT` / `UNKNOWN_OUTPUT`, `VARIABLE_TYPE_MISMATCH`, `PRIVATE_CONTAINER_REFERENCE` return to the main agent with `available_outputs` when the output set is known. Fix the child, then resubmit the full container.

Same-layer container children compile concurrently; Kahn layers stay serial. Public tool commits stay serial.

### 5. Retryable Failure Cascade Invariant (失败级联熔断)
- When a tool returns `ok=False` and `retryable=True` (e.g., `INVALID_NODE_CONFIG`, `NODE_NOT_FOUND`):
  - The loop **MUST** drop all remaining sibling calls in that batch.
  - The loop re-invokes the model with the error observation so the model can correct its mistake, rather than continuing on a broken intermediate graph.

### 6. Skill Isolation Invariant (技能激活隔离)
- If `activate_skills` is present in a turn's tool calls, it **MUST** be the sole tool executed in that turn (`calls = [activation_call]`).
- Any sibling tool calls are discarded. Newly activated skills must be injected into the prompt before the model attempts to use their procedures.

---

## 5. Type System & Graph Representation

### `MinimalGraphDict` vs `GraphDict`

There are two distinct graph types in this package:

1. **`MinimalGraphDict` (`graph/types.py`)**:
   - Represents in-progress candidate graphs manipulated by the Agent.
   - Nodes contain only `id`, `data`, and optional `parentId`.
   - Edges contain only `source`, `target`, and optional `sourceHandle`.
   - Deliberately omits layout coordinates (`position`), dimensions (`width`/`height`), and visual edge IDs so type checkers prevent assuming ReactFlow fields exist before layout.
2. **`GraphDict` (`types.py`)**:
   - The fully-hydrated, structurally-valid ReactFlow graph.
   - Produced exclusively by [`graph_postprocessor.postprocess_graph`](graph/graph_postprocessor.py).
   - Filled with layout coordinates, sanitized IDs, default viewports, and edge connection handles.

### Node Config Compilation Rules
- **Tool Nodes**: Compiled deterministically by `tool_parameter_normalize.compile_tool_node_config` using tenant tool catalogue schemas. Does **not** invoke LLM. Public entry: `build_tool_node`.
- **Agent Nodes (v2)**: Validated for `version=2`, `dify_agent`, `agent_task`, an exact enabled model identity, and complete Tool/MCP schemas. A complete Agent intent always writes `dify_tools`, including an empty list, so updates can clear stale Soul tools. Knowledge remains an inline Agent binding. Public entry: `build_agent_node`.
- **Loop / Iteration**: Compiled by `compile_container_subgraph` with child refs, then atomically replaced from canonical container data. Loop break-condition `varType` values are resolved from the variable registry rather than guessed from literals. Iteration child results use the shared aggregation rules, including `boolean` → `array[boolean]`. Public entries: `build_loop`, `build_iteration`.
- **Other Built-in Nodes**: Dispatched to `node_builder.build_single_node` which invokes LLM with specialized prompts from `prompts/nodes.md`. Public entry: `build_node`.

---

## 6. Testing & Quality Standards

### Running Unit Tests

Always run tests using `uv run --project api`:

```bash
# Run all generator tests
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/

# Run agent loop & tool tests (vital when touching agent/)
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/agent/test_loop.py
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/agent/test_tools.py
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/agent/test_compaction.py

# Run pipeline & postprocessor tests
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/test_runner.py
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/test_graph_postprocessor.py
uv run --project api pytest api/tests/unit_tests/core/workflow/generator/test_graph_validator.py
```

### Test Practices
- Use Arrange-Act-Assert structure.
- When adding new tools or node types, add matching unit tests for:
  1. Success path (happy path with correct schema and `changed=True`).
  2. Expected error path with proper `error_code` and `retryable` status.
  3. Structural validation in `graph_validator.py`.
  4. Variable references resolution in `variable_references.py`.

---

## 7. Checklist Before Submitting Edits

- [ ] **No Service Imports**: Confirmed zero imports from `services.*` or `models.*`.
- [ ] **Type Annotations**: Strict typing maintained; used `TypedDict`, `Protocol`, or explicit dataclasses (no raw untyped `dict` where keys are known).
- [ ] **Invariants Preserved**: State machine invariants (Section 4) verified against test suite.
- [ ] **Node ID Sanitization**: All node ID generation and variable resolution strictly match `[a-zA-Z0-9_]`.
- [ ] **All Tests Pass**: Ran pytest on `api/tests/unit_tests/core/workflow/generator/` and passed 100%.

## Live acceptance invariant

`ask_user` with `live_run_consent` emits a server-generated `execution_request`.
Only the service-owned `authorize_live_acceptance(revision, graph_hash)` callback
can reserve a live run. The service validates the pending request, owner, current
graph and worker lease, and durably consumes it before execution. Ordinary text,
changed candidates, subsequent turns and failed-step retries do not inherit grants.
A grant allows one case; the graph engine caps steps and cooperative elapsed time.
Nested provider calls retain their own limits and cannot be treated as a monetary cap.
