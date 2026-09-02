---
name: repair-validation
description: Repair a candidate graph after validate_graph, run_acceptance, or finish reports errors. Use when last_validation is invalid or last_acceptance.passed is false.
---

# Repair validation

1. Read `last_validation` and `last_acceptance` in CurrentSituation. Treat each `code@node_id` or failed node as the next observation, not as a completed turn.
2. In the same model reply as any narration, `read_node` on every listed node_id (and `read_graph` if an error has no node). Do not rebuild the whole graph unless the topology itself is wrong.
3. Fix with `build_node(mode=update)` for config, `replace` only to change type, `connect` / `disconnect` / `delete_node` for edges and extras.
4. `validate_graph` again. If `repeated_after_repair` is true, change approach — do not repeat the same mutation.
5. After structure passes, `run_acceptance` (default simulated). If it fails, `inspect_attempt` then repair the failed nodes and run again. If the result is `LIVE_RUN_REQUIRES_CONSENT`, only `ask_user` with question id `live_run_consent` — do not pretend acceptance passed. `finish` only when acceptance passed on this revision. A single tool error is not `fail`.
