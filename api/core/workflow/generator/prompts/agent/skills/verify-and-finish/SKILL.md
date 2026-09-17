---
name: verify-and-finish
description: Use when construction or repair is ready for graph validation, acceptance, and completion.
---

# Verify and finish

1. Confirm the intended nodes, edges, final outputs, and edit scope against the
   current contract. For non-legacy sessions, resolve remaining plan items and
   submit a complete contract before final verification.
   Complete when construction is accounted for and the contract is complete.
2. Call validate_graph and read content.valid and reported issues. Use
   repair-validation for deterministic failures. Check any returned contract_report
   for missing/conflicting requirements; natural-language effects may stay unverified.
   Complete when current graph validation passes and reported structural contract
   failures are resolved.
3. Call run_acceptance with server-held cases. Default to ["default"]; use other
   case IDs only when explicitly supplied by the server, never invented samples.
   Default to simulated; live mode follows the system live_run_consent rule.
   Read passed, executed_node_ids, unexecuted_node_ids, runtime_contract_passed,
   business_verified, and the reported revision/hash. inspect_attempt on failures;
   distinguish external failures from graph/configuration errors.
   Complete when acceptance passes for the resulting candidate and its actual
   verification level is known. Simulated success does not prove real execution.
4. Account for hydration and any later mutations. If hydration changed the graph,
   refresh validation for that revision; reuse only acceptance already bound to
   the resulting graph and current contract. A subsequent graph or contract edit
   requires fresh checks and acceptance. Let server freshness checks decide;
   do not manufacture hashes or rewrite evidence.
   Complete when validation and acceptance support the same current candidate.
5. Call finish with an evidence-grounded summary. Inspect a rejection's
   content.valid, contract_report, and acceptance even without an error_code.
   Return to repair-validation or the necessary verification step on failure.
   Complete only when finish.ok=true. Report actual execution coverage and whether
   business outcomes remain unverified. The service performs Apply separately.
