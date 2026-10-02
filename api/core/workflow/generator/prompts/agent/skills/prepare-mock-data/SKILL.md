---
name: prepare-mock-data
description: Use to prepare mock execution data.
---

# Prepare mock data

1. Call inspect_mock_targets. Without node_id it covers every external node; pass
   node_id for a run_node upstream node. Read output_schema, placeholder,
   instruction_excerpt and consumers.
2. Match the schema exactly: same output names and types; enum fields take one of
   the listed values. File outputs cannot be mocked; leave them out.
3. Ground the values, in this order: examples the user gave in the conversation;
   what instruction_excerpt says the node should produce for the chosen
   start_inputs; values that exercise the consumers (text that downstream code
   parses, values if-else compares). Write content in the user's language.
4. Cover branches deliberately. For each if-else condition in consumers, decide
   which case this run should take and set the value so it does. When both
   branches matter, run again with a value for the other case.
5. Keep fixtures small and honest: a few realistic sentences or records, no
   invented facts about the user's business beyond their examples.
6. INVALID_MOCK_OUTPUT names the node and field; fix only that value.
   MOCK_UNSUPPORTED_NODE means the whole-graph mock cannot run; test the
   downstream nodes with run_node and upstream_outputs, or go live.
