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
2. First pass on mock. Activate prepare-mock-data and follow it to write mocks,
   then call run_workflow(level=mock). Omitted outputs get typed placeholders,
   which only prove wiring.
3. Live pass when it matters. If the answer depends on real model or tool
   behaviour, call run_workflow(level=live). LIVE_RUN_REQUIRES_CONSENT means
   ask_user with question id live_run_consent; the run waits for the user and the
   next turn may retry live. EXECUTION_CONSENT_DENIED means the user did not
   approve: keep testing on mock and do not ask again while this graph remains
   in always_ask. A later user turn in always_execute clears that decline.
   A mock or local_only pass is still a valid place to stop.
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
   reached (live, mock or local_only) and what was not verified. Known limits:
   question-classifier and human-input cannot be mocked in a whole-graph run, file
   outputs cannot be mocked, and live runs stop at 32 steps or 60 seconds.
