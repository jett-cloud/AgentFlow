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
   Question Classifier classes are expanded into mock branch scenarios. Human Input
   forces simulated execution: the service pauses once, clones the runtime snapshot,
   submits every declared action and resumes each path. Only nodes without a registered
   verification capability return execution_status=skipped,
   verification_level=structural_only and blocked_nodes.
3. Handle consent. LIVE_RUN_REQUIRES_CONSENT means ask_user with question id
   live_run_consent; the run waits for the user. On the next turn, call
   run_workflow again. Approval selects live. Decline selects mock and must never
   be upgraded to live. Before the declined retry, activate prepare-mock-data and
   supply realistic mocks when they improve coverage; omitted outputs get typed
   placeholders, which only prove wiring. A later turn in always_execute clears
   the decline and selects live automatically.
4. Read scenarios. Require every classifier class and Human Input action path to
   pass; use selections and executed_node_ids to confirm the intended destination.
   When execution_status=skipped, do not remove or replace the unknown-capability
   nodes merely to pass verification. Disclose every unexecuted node and do not
   claim runtime or business verification.
5. Judge the outputs, not passed. passed=true only means the engine ran without
   failures. Compare graph_outputs and node_outputs with what the user asked for:
   required fields present, format, language, branch taken, obvious nonsense.
   mocked_outputs are your own fixtures, never evidence about real models or tools.
6. Repair. Read failed_nodes; category credential, quota or network is an
   environment issue to report, not a graph bug. For graph issues, repair with the
   build and connect tools, run validate_graph, then run_node(node_id=<repaired>)
   with upstream_outputs from the last run to confirm the fix, then run_workflow again.
   Nodes inside loops or iterations are checked with run_workflow only.
7. Bound the loop. Stop after three repair rounds without progress and report what
   still fails. Do not re-run an unchanged candidate hoping for a different result.
8. Hand off. When satisfied, activate verify-and-finish; run_acceptance stays in
   its default simulated mode. In the finish summary state the verification level
   selected (live, mock, local_only or structural_only) and what was not verified.
   Known limits: scenarios are bounded, Human Input file fields need real files and
   cannot receive synthetic values, file outputs cannot be mocked, and live runs stop
   at 32 steps or 60 seconds.
