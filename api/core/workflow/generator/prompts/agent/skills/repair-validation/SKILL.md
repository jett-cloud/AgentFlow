---
name: repair-validation
description: Use after a plan, builder, graph check, acceptance, or finish rejection.
---

# Repair validation

1. Read the failed result and CurrentSituation. Inspect error_code and field path,
   expected/actual values, cause, available_variables/available_outputs, and
   content.valid/contract_report/acceptance even if error_code is absent.
   Complete when the failed operation, actual commit state, and next repair target
   are identified. retryable alone does not determine the recovery action.
2. Choose the repair using authoritative observations:
   - Contract revision or base conflict: refresh current facts before resubmitting.
     For PLAN_MUTATION_MISMATCH, fix a mistaken call to match the contract, or
     revise the contract for a justified design change. Preserve explicit user
     requirements; removing them just to pass is not a repair.
   - Rejected create: no new node committed. For an absent ID, correct the payload
     and retry create with the same ID. NODE_EXISTS instead requires read_node
     and an operation consistent with the requested edit.
   - Rejected update: read_node, preserve non-target fields, retry update.
     Rejected replace: preserve the original state and retry replace.
     Wrong builder: use the specialized builder for the confirmed type.
   - INVALID_NODE_CONFIG: use the reported field path and inspect_node_schema.
     For an ordinary node, resubmit build_node with corrected intent/structure.
     Do not patch raw node JSON. INTENT_INPUT_MISSING, INTENT_OUTPUT_MISSING,
     and INTENT_OUTPUT_TYPE_MISMATCH require matching actual bindings/types.
   - UNKNOWN_OUTPUT or unknown producer: inspect confirmed outputs or build the
     missing planned producer. DEPENDENCY_ORDER_REQUIRED needs producer-first
     submission using actual commit state. REFERENCE_NOT_AVAILABLE also requires
     checking control-flow branches; PRIVATE_CONTAINER_REFERENCE needs legal
     public outputs, not merely a different ordering.
   - Container failure: activate build-container, fix the reported child/field,
     and resubmit the full container. Preserve successful children.
   - Resource missing or unavailable: inspect exact identity/catalogue/schema.
     Ask for a material alternative only when user judgment is required; use
     the system stopping rules for an unrecoverable capability failure.
   - Acceptance failure: inspect_attempt to distinguish configuration, actual
     runtime output, business assertion, external service, and policy failures.
     Follow the system's consent rule for LIVE_RUN_REQUIRES_CONSENT.
   Complete when the chosen action addresses the reported cause without weakening
   the user's contract or pretending an external dependency is available.
3. Execute the correction within budget. If repeated_after_repair is true, gather
   new facts or change the repair; do not replay the same failed mutation.
   For a Document Extractor file/file-list mismatch, change the Start input only
   if the user intended an upload; otherwise correct variable_selector.
   Complete when the failed operation succeeds or a concrete user/terminal
   dependency is reported according to the system rules.
4. Resume unfinished construction with its create/edit/container skill. When the
   candidate is ready, activate verify-and-finish to obtain fresh checks and
   evidence. Repair success alone does not complete the workflow.
