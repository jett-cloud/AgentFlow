# Tool plugin generator operations

Generation and Agent turns use workspace-configured LLM providers (the same pool
as workflow LLM / Agent nodes). Agent turns require an explicit `model_provider`
and `model` with native Function Calling support.

Iterative editing uses `POST /workspaces/current/tool-plugin/agent/turn` (or its
streaming variant). The Agent can read, write, bootstrap, add tools, and run
static validation. It never installs or invokes the generated plugin.

Publishing is an explicit user action through
`POST /workspaces/current/tool-plugin/sessions/{session_id}/publish`. The API
checks the session revision, installs the session-owned candidate, invokes the
active tool with request-scoped credentials, and restores the last published
source when verification fails. A failed candidate never deletes the draft.

Installation packages generated source with the official Dify Plugin CLI. Set
`DIFY_PLUGIN_CLI_PATH` to the CLI executable's absolute path in the API process
environment, for example:

```text
DIFY_PLUGIN_CLI_PATH=/usr/local/bin/dify
```

The packager fails closed when the setting is absent:

```text
DIFY_PLUGIN_CLI_PATH is not configured; install the Dify Plugin CLI and set this variable to its binary path.
```

If the configured file does not exist, it reports:

```text
Dify Plugin CLI binary not found at <path>; install the CLI and update DIFY_PLUGIN_CLI_PATH.
```
