---
name: test-and-evaluate
description: Use only after the workflow is fully built and validated. Never use while nodes are still being created.
---

# Test and evaluate

0. Gate. Continue only when all hold for the current candidate_revision: the
   contract is complete, no planned node is still unbuilt, and the latest
   validate_graph returned content.valid=true. Otherwise leave this skill and
   finish construction or use repair-validation. Any later mutation reopens the gate.
1. Pick inputs. Derive start_inputs from the user's request and any examples in
   the conversation; use realistic values, not "test". With no examples, pick one
   typical case in the user's language.
2. Run once. Call run_workflow without a level. The system chooses the strategy:
   graphs without external calls run local_only, always_execute or a one-shot
   grant runs external nodes live, and a decline for the current graph runs mock.
3. Handle consent. LIVE_RUN_REQUIRES_CONSENT means ask_user with question id
   live_run_consent; the run waits for the user. On the next turn, call
   run_workflow again. Approval selects live. Decline selects mock and must never
   be upgraded to live. Before the declined retry, activate prepare-mock-data and
   supply realistic mocks when they improve coverage; omitted outputs get typed
   placeholders, which only prove wiring. A later turn in always_execute clears
   the decline and selects live automatically.
4. Judge the outputs, not passed. passed=true only means the engine ran without
   failures. Compare graph_outputs and node_outputs with what the user asked for:
   required fields present, format, language, branch taken, obvious nonsense.
   mocked_outputs are your own fixtures, never evidence about real models or tools.
5. Repair. Read failed_nodes; category credential, quota or network is an
   environment issue to report, not a graph bug. For graph issues, repair with the
   build and connect tools, run validate_graph, then run_node(node_id=<repaired>)
   with upstream_outputs from the last run to confirm the fix, then run_workflow again.
   Nodes inside loops or iterations are checked with run_workflow only.
6. Bound the loop. Stop after three repair rounds without progress and report what
   still fails. Do not re-run an unchanged candidate hoping for a different result.
7. Hand off. When satisfied, activate verify-and-finish; run_acceptance stays in
   its default simulated mode. In the finish summary state the verification level
   selected (live, mock or local_only) and what was not verified. Known limits:
   question-classifier and human-input cannot be mocked in a whole-graph run, file
   outputs cannot be mocked, and live runs stop at 32 steps or 60 seconds.
