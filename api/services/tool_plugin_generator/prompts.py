from __future__ import annotations

from typing import Any, Literal

AgentMode = Literal["first_tool", "add_nth_tool", "edit_existing"]

FILL_JSON_SCHEMA = """{
  "provider_label": "Human-readable provider name",
  "tool_label": "Human-readable tool name",
  "tool_description": "What the tool does",
  "parameters": [
    {
      "name": "param_name",
      "type": "string",
      "required": true,
      "label": {"en_US": "Param Label"},
      "human_description": {"en_US": "Shown in the UI"},
      "llm_description": "Hints for the LLM when calling the tool",
      "form": "llm"
    }
  ],
  "credentials": [
    {"name": "api_key", "type": "secret-input", "required": true, "label": {"en_US": "API Key"}}
  ],
  "invoke_python_body": "yield self.create_text_message(...)",
  "readme": "# Plugin README in markdown"
}"""

_ADD_TOOL_HINTS = (
    "新增工具",
    "添加工具",
    "第二个工具",
    "再加一个工具",
    "add tool",
    "another tool",
    "new tool",
)


def infer_agent_mode(
    *,
    files_empty: bool,
    intent: str | None,
    user_message: str,
) -> AgentMode:
    if files_empty:
        return "first_tool"
    normalized_intent = (intent or "").strip().lower()
    if normalized_intent in {"add_tool", "add_nth_tool"}:
        return "add_nth_tool"
    text = (user_message or "").lower()
    if any(hint in (user_message or "") or hint in text for hint in _ADD_TOOL_HINTS):
        return "add_nth_tool"
    return "edit_existing"


def build_fill_prompt(
    *,
    author: str,
    plugin_name: str,
    tool_name: str,
    user_prompt: str,
    api_doc: str,
) -> str:
    return f"""You are generating fill values for a Dify tool plugin scaffold.

Author: {author}
Plugin name: {plugin_name}
Tool name: {tool_name}

User request:
{user_prompt}

API documentation:
{api_doc}

Respond with JSON only (no markdown fences) matching this schema:
{FILL_JSON_SCHEMA}

Rules:
- invoke_python_body must be ONLY the indented body statements of `_invoke`
  (no `def`, no class). Use consistent 4-space indentation inside the body.
- The body MUST `yield self.create_text_message(...)` (or other ToolInvokeMessage helpers).
- Good example body:
  text = tool_parameters.get("text", "")
  yield self.create_text_message(str(text))
- Bad example (do NOT do this — wrong indent / includes def):
  def _invoke(...):
      yield self.create_text_message("x")
- parameters entries must include name, type, required, label (i18n object), and form
  (form must be "llm" or "form"; prefer "llm")
- Every i18n label/description (manifest, provider identity, tool identity, credentials)
  MUST include en_US; zh_Hans alone is invalid. Prefer both en_US and zh_Hans.
- credentials entries must include name; use an empty list if none are needed
- Never hardcode API secrets in invoke_python_body; read from credentials when needed
- readme should be concise markdown for the plugin
"""


def build_agent_system_prompt(state: dict[str, Any]) -> str:
    mode = state.get("mode") or "edit_existing"
    existing_tools = state.get("existing_tools") or []
    paths = state.get("paths") or []
    path_preview = ", ".join(paths[:40])
    if len(paths) > 40:
        path_preview += f", …(+{len(paths) - 40})"

    workflow = {
        "first_tool": (
            "1) Call bootstrap_scaffold with the user request (and api_doc if any).\n"
            "2) Optionally read/write to fix issues.\n"
            "3) When the first tool is complete, call validate.\n"
            "4) If validation fails, fix files then validate again.\n"
            "5) Stop tool_calls and summarize the draft in Chinese."
        ),
        "add_nth_tool": (
            "1) Call add_tool (never bootstrap_scaffold; never change plugin identity).\n"
            "2) Read/write only as needed to finish the new tool.\n"
            "3) When that new tool is complete, call validate.\n"
            "4) On failure, repair then validate again.\n"
            "5) Stop and summarize the draft in Chinese."
        ),
        "edit_existing": (
            "1) Prefer read_file before write_file; keep edits minimal.\n"
            "2) Do not bootstrap_scaffold.\n"
            "3) When the requested change is complete, you MUST call validate.\n"
            "4) Only write_file without validate means the work is incomplete.\n"
            "5) On failure, repair then validate again.\n"
            "6) Stop and summarize the draft in Chinese."
        ),
    }.get(str(mode), "")

    last_validate = str(state.get("last_validate") or "")
    last_test = str(state.get("last_test") or "")
    file_api_retry_hint = ""
    combined_feedback = f"{last_validate}\n{last_test}".lower()
    if any(
        marker in combined_feedback
        for marker in (
            "fetch_file",
            "failed to read file",
            "create_image_message(blob=",
            "self.session.post",
            "self.session.get",
            ".blob",
        )
    ):
        file_api_retry_hint = """
## Urgent fix from last validate/test
- Do NOT call `self.fetch_file` (it does not exist on Tool).
- File parameters are already `File` objects: read bytes with `.blob`, name with `.filename`.
- Return image bytes with `create_blob_message(blob=..., meta={"mime_type": "image/png"})`.
- HTTP must use `httpx`/`requests`, never `self.session.post/get`.
"""

    return f"""You are a Dify Tool plugin editor agent.
Goal: implement or fix HTTP/API tools inside a fixed plugin scaffold using tools.

## Current workspace
- mode: {mode}
- author: {state.get("author")}
- plugin_name: {state.get("plugin_name")}
- plugin_identity_locked: {state.get("plugin_identity_locked")}
- active_tool_name: {state.get("active_tool_name")}
- files_empty: {state.get("files_empty")}
- file_count: {state.get("file_count")}
- existing_tools: {existing_tools}
- tool_count: {state.get("tool_count")}
- paths: [{path_preview}]
- has_published_version: {state.get("has_published_version")}
- credentials_required: {state.get("credentials_required")}
- last_validate: {state.get("last_validate")}
- last_test: {state.get("last_test")}
- iterations_left: {state.get("iterations_left")}
{file_api_retry_hint}
## Workflow for this mode
{workflow}

## Hard rules
- Only edit allowed scaffold paths (manifest.yaml, main.py, requirements.txt,
  README.md, .env.example, provider/, tools/, _assets/).
- main.py must stay exactly: `from dify_plugin import Plugin, DifyPluginEnv`, then
  `plugin = Plugin(DifyPluginEnv())`, then `plugin.run()`. Never write bare `Plugin()`.
- provider/*.yaml MUST include `tools: [tools/<tool>.yaml]` and
  `extra: {{python: {{source: provider/<name>.py}}}}`. tools/*.yaml MUST include
  `extra: {{python: {{source: tools/<tool>.py}}}}`.
- Never invent directory layouts; never use shell/subprocess/os.system; never delete files.
- tools/*.py `_invoke` must be valid Python.
- HTTP calls: NEVER use `self.session.post/get/request` (`self.session` is the plugin
  runtime Session, not HTTP). Use `httpx` or `requests` clients.
- File parameters: NEVER invent `self.fetch_file` or a `binary` dict field. The parameter is already a File object.
  Correct pattern:
  ```python
  image = tool_parameters["image_file"]  # File
  data = image.blob
  name = image.filename or "image.png"
  # HTTP with httpx/requests — not self.session
  yield self.create_blob_message(blob=out, meta={{"mime_type": "image/png"}})
  ```
- Returning image bytes: use
  `create_blob_message(blob=..., meta={{"mime_type": "image/png"}})`.
  `create_image_message` accepts a URL string only; never pass `blob=` to it.
- Do not invent explanations like "import requests pollutes the runtime namespace"; fix real API misuse instead.
- Do not hardcode secrets. Define provider credential fields when needed, but never
  request or use real credential values.
- Call validate when a deliverable unit is finished, NOT after every write_file.
- Agent output is a draft. Never claim it is installed, tested against an external API, or live.
- Do not pad iterations; when done, respond without tool_calls.
- Final user-facing summary: 2–4 sentences in Chinese.
"""
