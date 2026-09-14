# Node config snippets

Loaded one type at a time by inspect_node_schema / node builders. Do not dump this whole file into the live agent system prompt.

## start

- start:
    {"variables": [
       {"variable": "url",   "label": "URL",   "type": "text-input",
        "required": true,  "max_length": 256,  "options": []},
       {"variable": "topic", "label": "Topic", "type": "paragraph",
        "required": false, "max_length": 4096, "options": []},
       {"variable": "enabled", "label": "Enabled", "type": "checkbox",
        "required": false, "default": false},
       {"variable": "payload", "label": "Payload", "type": "json_object",
        "required": true,
        "json_schema": {"type": "object",
                        "properties": {"name": {"type": "string"}}}},
       {"variable": "doc",   "label": "Document", "type": "file",
        "required": true,
        "allowed_file_types": ["document"],
        "allowed_file_upload_methods": ["local_file", "remote_url"],
        "allowed_file_extensions": []}
    ]}
    EVERY user-supplied value referenced by a downstream node
    (``{{#node-id.var#}}`` in a prompt / answer / template, or
    ``["node-id", "var"]`` in a value_selector / iterator_selector /
    tool_parameters) MUST be declared here as an entry of ``variables``.
    If the planner's ``start_inputs`` list is non-empty, use it verbatim
    (the user prompt section "Start inputs" surfaces it). Types:
    text-input | paragraph | select | number | file | file-list | checkbox |
    json_object. Always use ``json_object``; never use ``json-object``.
    For a "file" or "file-list" variable you MUST also set
    ``allowed_file_types`` to a NON-EMPTY subset of
    ["document", "image", "audio", "video", "custom"] — it is a REQUIRED
    field and the draft fails to load (showing "supported file types is
    required") without it. Choose by purpose: ["document"] for text
    extraction (PDF / Word / PPT / Markdown / …), ["image"] for vision,
    etc. Always set ``allowed_file_upload_methods`` to
    ["local_file", "remote_url"]. Only when you include "custom" must you
    also set ``allowed_file_extensions`` to a non-empty list like
    [".epub", ".rtf"]; otherwise leave it [].
    In Advanced-Chat mode ``sys.query`` is automatic. ``sys.files`` exists in
    both Workflow and Advanced-Chat. Downstream nodes may reference the
    system variables that the matching runner injects; do NOT add them to
    ``variables``.
    Outputs: each ``variables[].variable`` name (e.g. ``url``, ``topic``).

## end

- end (Workflow mode only):
    {"outputs": [
        {"variable": "result", "value_selector": ["<src-node-id>", "<out-var>"],
         "value_type": "string"}
    ]}
    `outputs` MUST contain at least one output. Every item requires a unique
    `variable`, a two-or-more-part `value_selector`, and `value_type` matching
    the selected source variable. Legal values are ``string``, ``number``,
    ``integer``, ``secret``, ``boolean``, ``object``, ``file``, ``array``,
    ``array[string]``, ``array[number]``, ``array[object]``,
    ``array[boolean]``, ``array[file]``, ``any``, and ``array[any]``.
    An End node must not have outgoing edges.
    Selectable outputs: none. Downstream cannot reference an end node.

## answer

- answer (Advanced Chat mode only):
    {"variables": [],
     "answer": "<text with {{#<src>.<var>#}} placeholders>"}
    `answer` MUST contain non-blank reply content and may contain
    ``{{#<src>.<var>#}}`` placeholders.
    Selectable outputs: none; an Answer node may continue to downstream nodes
    through its ordinary control-flow source edge.

## llm

- llm:
    {"model": {"provider": "<provider>", "name": "<model>", "mode": "chat",
               "completion_params": {"temperature": 0.7}},
     "prompt_template": [
       {"role": "system", "text": "<system prompt>"},
       {"role": "user",   "text": "<user prompt with {{#<src>.<var>#}}>"}
     ],
     "context": {"enabled": false, "variable_selector": []},
     "vision": {"enabled": false}}
    Selectable outputs: ``text``, ``reasoning_content``, ``usage``.
    Enabling ``structured_output_enabled`` also declares nested
    ``structured_output`` (even with empty ``properties``). Set
    ``structured_output``: {"schema": {"type": "object",
    "properties": {"<name>": {"type": "string"}}}} for fields. Downstream may
    read ``["<llm-id>", "text"]``, ``["<llm-id>", "reasoning_content"]``,
    ``["<llm-id>", "usage"]``, ``["<llm-id>", "structured_output"]``, or
    ``["<llm-id>", "structured_output", "<name>"]``. Schema properties are NOT
    extra top-level outputs. Prefer this over a follow-on code node when the
    user wants JSON.

    Prompt-writing rules for the user-message text:
      * ``{{#node.var#}}`` placeholders are interpolated by Dify BEFORE the
        LLM sees them — at run time the model only sees the resolved value.
        So an instruction like "Translate this: {{#node1.text#}}" is read
        by the LLM as "Translate this: <the actual text>".
      * NEVER include placeholder syntax inside an "example output" block
        in your prompt — the LLM will treat the example as the literal
        answer template and echo placeholders back as output. Wrong:
            Output JSON: {"en": "{{#node1.text#}}", "es": "{{#node1.text#}}"}
        Right:
            Translate the input into English, Spanish, French, German.
            Output a JSON object with keys "en", "es", "fr", "de" whose
            values are the translations.
            Input: {{#node1.text#}}
      * Each placeholder only resolves the variable from its source node —
        it cannot be a Jinja template or call a function.

## knowledge-retrieval

- knowledge-retrieval:
    {"query_variable_selector": ["<src>", "<var>"],
     "query_attachment_selector": [],
     "dataset_ids": ["<installed-dataset-id>"],
     "retrieval_mode": "multiple",
     "multiple_retrieval_config": {"top_k": 4, "score_threshold": null,
                                   "reranking_enable": false}}
    When available knowledge bases are supplied, dataset_ids MUST be a non-empty
    subset of their exact ids. Do not invent or use unlisted dataset ids.
    Configure at least one of query_variable_selector or query_attachment_selector.
    single requires single_retrieval_config.model.
    multiple requires multiple_retrieval_config.
    When reranking_mode is reranking_model and reranking_enable is true,
    provide reranking_model {provider, model}.
    When reranking_mode is weighted_score, provide vector_setting and keyword_setting
    weights summing to 1, including the vector embedding provider/model.
    metadata_filtering_mode is disabled, automatic, or manual; automatic requires
    metadata_model_config and manual requires metadata_filtering_conditions.
    Outputs: ``result`` (array of chunks). Nested fields: ``result`` then
    ``content`` / ``title`` via a code node or ``{{#<id>.result#}}``.

## code

- code  (escape hatch — only if no installed tool fits):
    {"code_language": "python3",
     "code": "def main(arg1: str) -> dict:\n    return {'result': arg1}",
     "variables": [{"variable": "arg1", "value_selector": ["<src>", "<var>"]}],
     "outputs": {"result": {"type": "string", "children": null}}}
    ``outputs`` keys are the node's output names. ``type`` MUST be one of:
    string | number | object | boolean | array[string] | array[number] |
    array[object] | array[boolean]. Do NOT use ``array``, ``any``,
    ``array[any]``, ``integer``, or ``file``.
    ``code`` MUST contain non-empty executable source.
    Every ``variables[].variable`` MUST match ``^[A-Za-z_][A-Za-z0-9_]*$``
    and be unique. Every ``value_selector`` MUST contain at least two
    non-empty strings: the source node id and its variable path.
    ``"outputs": {}`` is legal when the code returns no declared values.
    Outputs: each key of ``outputs`` (example: ``result``).

## template-transform

- template-transform:
    {"template": "Hello {{ name }}",
     "variables": [{"variable": "name", "value_selector": ["<src>", "<var>"]}]}
    ``template`` MUST contain non-empty Jinja2 source.
    ``variables`` may be empty. Every declared ``variables[].variable`` MUST
    match ``^[A-Za-z_][A-Za-z0-9_]*$``, be at most 30 characters, and be unique.
    Every ``value_selector`` MUST contain at least two non-empty strings:
    the source node id and its variable path.
    Template uses Jinja2 ``{{ variable }}`` names from ``variables[].variable``,
    not Dify placeholders ``{{#node.var#}}``.
    Outputs: output

## http-request

- http-request  (escape hatch — only if no installed tool fits):
    {"variables": [], "method": "get", "url": "https://example.com",
     "authorization": {"type": "no-auth", "config": null},
     "headers": "", "params": "",
     "body": {"type": "none", "data": []},
     "ssl_verify": true,
     "timeout": {"connect": 0, "read": 0, "write": 0},
     "retry_config": {"retry_enabled": true, "max_retries": 3,
                      "retry_interval": 100}}
    URL must be non-empty. ``method`` is one of get/post/put/patch/delete/head/options.
    API-key auth is ``{"type":"api-key","config":{"type":"basic","api_key":"<key>","header":""}}``;
    config ``type`` must be one of ``basic``, ``bearer``, or ``custom`` (custom uses ``header``).
    Body ``data`` is a list of ``{"type":"text","key":"","value":"..."}`` or ``{"type":"file","key":"","file":["<node>","<file>"]}`` items.
    This node is ``simulate_always`` during acceptance; never claim its external request ran.
    Outputs: ``body``, ``status_code``, ``headers``, ``files``.

## tool

- tool  (PREFERRED for external actions when listed in Available tools):
    {"provider_id": "<provider>",
     "provider_type": "builtin",             # exact value from catalogue
     "provider_name": "<provider>",
     "tool_name": "<tool>",
     "tool_label": "<Tool>",
     "tool_node_version": "2",
     "tool_configurations": {},
     "tool_parameters": {"<param>": {"type": "mixed",
                                     "value": "{{#<src>.<var>#}}"}}}
    Binding MUST come from ``inspect_tool``. Copy identity fields as the
    exact value from catalogue; never guess provider_type, provider_id, or
    tool_name. Prefer an installed tool over http-request.
    Parameter ``type`` is one of:
      "mixed"    — string template referencing variables ({{#...#}})
      "variable" — direct reference, value is ["<src>", "<var>"]
      "constant" — literal JSON (keep ``false`` / ``0`` / empty string)
    File parameters MUST use ``variable`` selectors. Schema defaults may be
    omitted so the compiler fills them. Do not emit unknown arguments.
    Do not invent output names; use catalogue ``output_names`` / schema only.
    This node is ``metered``. Simulated acceptance must not claim a real tool
    call ran.

## agent

- agent (Dify Agent Node v2):
    {"type": "agent", "version": "2", "agent_node_kind": "dify_agent",
     "title": "<label>",
     "agent_task": "<what the agent must accomplish>",
     "agent_binding": {"binding_type": "inline_agent"},
     "dify_tools": [
       {"provider_type": "mcp", "provider_id": "<server_id>", "tool_name": null,
        "credential_type": "unauthorized"},
       {"provider_type": "builtin", "provider_id": "<provider>", "tool_name": "<tool>",
        "credential_type": "unauthorized"}
     ],
     "model": {"provider": "<p>", "name": "<m>", "mode": "chat",
               "completion_params": {"temperature": 0.7}}}
    Do NOT invent agent_id / current_snapshot_id — leave binding without ids
    (orchestrator hydrates later). Use agent when the step needs tool use,
    multi-step reasoning, or understanding upstream images; otherwise prefer llm/tool.
    ``dify_tools`` is optional Soul tool config. Identifiers MUST come from
    Available tools. MCP entries use provider_type "mcp" and the catalogue
    provider portion as provider_id; tool_name=null selects every tool from
    that MCP server. Omit dify_tools when the agent has no tools.
    Do not emit knowledge or knowledge.sets. Workflow Assist compiles Agent
    knowledge deterministically from build_agent_node after
    discarding any Builder-authored knowledge field.
    The main agent does not submit Dify envelopes for this node.
    Outputs: ``text``, ``files``, ``json`` by default (same as an empty
    ``agent_declared_outputs``). To expose other names, set
    ``agent_declared_outputs`` to
    [{"name": "<var>", "type": "string"|"number"|"object"|"array"|"file"|...}].
    Downstream nodes reference those names: ``{{#<agent-id>.text#}}`` or
    ``["<agent-id>", "text"]``. Do not treat an agent node as having zero outputs.

## if-else

- if-else:
    {"cases": [
       {"case_id": "true",
        "logical_operator": "and",
        "conditions": [{"id": "c1",
                        "varType": "<Dify variable type>",
                        "variable_selector": ["<src>", "<var>"],
                        "comparison_operator": "is",
                        "value": "<value>"}]}
     ]}
    ``cases`` is the branch source of truth. The first newly-created IF may use
    ``true``; every added ELIF uses a unique UUID. Every ``case_id`` must be
    non-empty and unique and must not be `false`. Display order, not the id,
    determines IF versus ELIF, so never rewrite an existing first UUID.
    ELSE is implicit: it has no case and its source handle is always ``false``.
    Case/ELIF source handles equal their ``case_id``. Do not emit
    ``_targetBranches``; the system derives that canvas metadata from cases.
    Every condition needs ``id``, ``varType``, a two-part-or-longer
    ``variable_selector``, ``comparison_operator``, and ``value``. Use the
    operator list for its variable type: string = contains | not contains |
    start with | end with | is | is not | empty | not empty; number/integer =
    = | ≠ | > | < | ≥ | ≤ | empty | not empty; boolean = is | is not; file =
    exists | not exists; scalar arrays = contains | not contains | empty |
    not empty; array/object = empty | not empty; arrayFile also supports all of
    and an optional ``sub_variable_condition``. ``is null`` / ``is not null``
    are accepted persisted unary operators. Prefer numeric comparison values as
    strings (for example ``"22"``); boolean values are JSON booleans.
    Outputs: none (control-flow).

## question-classifier

- question-classifier:
    {"query_variable_selector": ["<src>", "<var>"],
     "model": {"provider": "<p>", "name": "<m>", "mode": "chat",
               "completion_params": {"temperature": 0.7}},
     "classes": [{"id": "1", "name": "Topic A", "label": "CLASS 1"},
                 {"id": "2", "name": "Topic B", "label": "CLASS 2"}],
     "_targetBranches": [{"id": "1", "name": ""}, {"id": "2", "name": ""}],
     "vision": {"enabled": false},
     "instruction": ""}
    Source handle for downstream edges = the class_id ("1" / "2" / ...).
    Outputs: ``class_id``, ``class_name``.

## parameter-extractor

- parameter-extractor:
    {"query": ["<src>", "<var>"],           # one value_selector, not a list of them
     "model": {"provider": "<p>", "name": "<m>", "mode": "chat",
               "completion_params": {"temperature": 0.7}},
     "parameters": [{"name": "topic", "type": "string",
                     "description": "<purpose>", "required": true}],
     "reasoning_mode": "prompt",
     "vision": {"enabled": false},
     "instruction": ""}
    Each ``parameters[].name`` is an output. Legal ``type``: string | number |
    boolean | array[string] | array[number] | array[object] | array[boolean]
    (legacy aliases ``bool`` and ``select`` are also accepted).
    Outputs: each parameter name, plus ``__is_success``, ``__reason``,
    ``__usage``.

## document-extractor

- document-extractor:
    {"variable_selector": ["<src>", "<file-var>"]}  # a file / file-list input
    Single output variable ``text``: a string for a single file, or an array
    of strings for a file-list. Runtime determines this from the actual input;
    do not emit the legacy ``is_array_file`` field. ``variable_selector``
    MUST point at a ``start`` variable declared with type "file" / "file-list"
    (or ``sys.files`` in Advanced-Chat mode). That start variable MUST set a
    non-empty ``allowed_file_types`` (use ["document"] for document text).
    Outputs: ``text``.

## variable-aggregator

- variable-aggregator  (merge mutually-exclusive branches into one output):
    {"output_type": "string",        # VarType of the merged value — one of
                                     # string | number | object | array[string] |
                                     # array[number] | array[object] | file |
                                     # array[file] | any. Match the branch vars.
     "variables": [["<branchA-node>", "<var>"],
                   ["<branchB-node>", "<var>"]]}
    Output variable: ``output`` (the first branch that actually ran). Place it
    after an ``if-else`` / ``question-classifier`` to rejoin paths before the
    ``end`` / ``answer`` node. Each entry of ``variables`` is a value_selector
    array, NOT a placeholder string.
    Outputs: ``output``.

## list-operator

- list-operator  (filter / sort / slice an array variable):
    {"variable": ["<src>", "<array-var>"],
     "filter_by": {"enabled": false, "conditions": []},
     "extract_by": {"enabled": false, "serial": "1"},
     "order_by": {"enabled": false, "key": "", "value": "asc"},
     "limit": {"enabled": false, "size": 10}}
    Enable only the sub-features you need; ``conditions`` reuse the if-else
    condition shape (key / comparison_operator / value). Outputs: ``result``
    (the processed array), ``first_record``, ``last_record``.

## assigner

- assigner  (write to an existing conversation / loop variable):
    {"version": "2",
     "items": [{"variable_selector": ["<target-node>", "<target-var>"],
                "input_type": "variable",
                "operation": "over-write",
                "value": ["<source-node>", "<source-var>"]}]}
    ``input_type`` is "variable" (value is a selector) or "constant".
    Operations: over-write | clear | append | extend | set | += | -= | *= |
    /= | remove-first | remove-last.
    Outputs: none (writes an existing conversation/loop variable).

## human-input

- human-input  (pause for a person; use webapp delivery by default):
    {"delivery_methods": [{"type": "webapp", "enabled": true}],
     "form_content": "<short review / approval instructions>",
     "inputs": [{"type": "paragraph", "output_variable_name": "comment",
                 "default": {"type": "constant", "selector": [], "value": ""}}],
     "user_actions": [{"id": "approve", "title": "Approve",
                       "button_style": "primary"}],
     "timeout": 3, "timeout_unit": "day"}
    Default delivery is WebApp. Add Email only when the user asked for email
    and real recipients exist. Email config uses ``include_bound_group`` and
    member ``reference_id`` (never ``whole_workspace`` / ``user_id``). Do not
    invent member IDs or emails. Never generate Slack, Teams, or Discord.
    Trigger workflows cannot use WebApp; if Email recipients are also missing,
    ask for clarification instead of guessing.
    Supported ``inputs[].type`` values: paragraph, select, file, file-list.
    Each ``inputs[].output_variable_name`` is an output variable. Outgoing
    edges use the matching user-action id as ``sourceHandle``; timeout edges
    use ``__timeout``. Every action id must match ``^[A-Za-z_][A-Za-z0-9_]*$``,
    be unique, and stay within 20 characters. Do not emit ``_targetBranches``.
    New generated nodes use timeout ``3 day``. Backend ``36 hour`` is only the
    omit-fallback for old graphs that left timeout blank.
    Outputs: each ``inputs[].output_variable_name``, plus ``__action_id``,
    ``__action_value``, ``__rendered_content``. ``form_content`` may reference
    upstream variables and ``{{#$output.<name>#}}`` field tokens.

## iteration

- iteration:
    {"iterator_selector": ["<src>", "<list-var>"],
     "output_selector": ["<last-child>", "<out-var>"],
     "is_parallel": false, "parallel_nums": 10,
     "error_handle_mode": "terminated", "flatten_output": true}
    The generator supplies ``start_node_id``, child wrappers, and the synthetic
    ``iteration-start`` node; omit these system-owned fields. Submit Iteration
    through ``build_iteration`` with child ``ref`` values. The main agent must not emit
    ``iteration-start`` nodes, ``start_node_id``, ``iterator_input_type``,
    ``output_type``, ``_children``, or ``parentId``. ``iterator_input_type``
    and ``output_type`` are derived after selectors are repaired.
    ``parallel_nums`` must be at least 1.
    Child nodes inside this iteration read the current element as
    ``["<iter-id>", "item"]`` or, when that element is an object, a field
    ``["<iter-id>", "item", "<field>"]``. Object arrays cannot be drilled
    with ``rows.field``. The 0-based index is ``["<iter-id>", "index"]``.
    Nodes OUTSIDE the iteration must NOT use ``item`` / ``index``; they
    consume the aggregated ``output``.
    Outputs: ``output`` (aggregated). Child-scope only: ``item``, ``index``.

## loop

- loop:
    {"break_conditions": [{"id": "c1",
                            "variable_selector": ["<child>", "<var>"],
                            "comparison_operator": "is",
                            "value": "<value>"}],
     "loop_count": 10, "logical_operator": "and",
     "loop_variables": [{"label": "acc", "var_type": "string",
                         "value_type": "constant", "value": ""}]}
    The generator supplies ``start_node_id``, child wrappers, and the synthetic
    ``loop-start`` node; omit these system-owned fields. Submit Loop through
    ``build_loop`` with child ``ref`` values. The main agent must not emit
    ``loop-start`` nodes, ``start_node_id``, ``_children``, ``parentId``,
    or ``error_handle_mode``. Graphon 0.7 does not execute Loop error strategies.
    ``loop_count`` must be an integer from 1 to 100.
    ``loop_variables`` must be a list, never null. Each item must include ``value``.
    Children and downstream nodes read loop variables as
    ``["<loop-id>", "<label>"]``. There is no automatic ``output``, ``item``,
    or ``index`` unless you declare a loop variable with that label.
    ``loop_variables[].var_type`` uses the same whitelist as code outputs
    (string | number | object | boolean | array[string] | array[number] |
    array[object] | array[boolean]). When ``value_type`` is ``variable``,
    ``value`` is a selector; when ``constant``, ``value`` is a literal (do
    not put ``{{#...#}}`` in it).
    Outputs: each ``loop_variables[].label``.
