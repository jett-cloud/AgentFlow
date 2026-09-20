from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread
from typing import Any
from unittest.mock import Mock

import pytest

from graphon.model_runtime.entities.message_entities import PromptMessageTool, ToolPromptMessage
from graphon.model_runtime.entities.model_entities import ModelFeature
from services.tool_plugin_generator.agent_runner import (
    AgentBudgetExceededError,
    AgentCheckpointError,
    AgentLLMStep,
    AgentToolCall,
    AgentTurnLimits,
    TenantAgentLLMClient,
    hydrate_history_messages,
    iter_agent_turn,
    run_agent_turn,
)
from services.tool_plugin_generator.agent_tools import tool_schemas, tool_specs


@dataclass
class ScriptedLLM:
    steps: list[AgentLLMStep]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def next_step(self, *, messages: list[Any], tools: list[PromptMessageTool]) -> AgentLLMStep:
        self.calls.append({"messages": messages, "tools": tools})
        if not self.steps:
            return AgentLLMStep(content="done")
        return self.steps.pop(0)


class FakeModelInstance:
    def __init__(self, *, features: list[ModelFeature], content: str = "", tool_calls: list[Any] | None = None):
        self.features = features
        self.content = content
        self.tool_calls = tool_calls or []
        self.last_kwargs: dict[str, Any] = {}

    def get_model_schema(self):
        return Mock(features=self.features)

    def invoke_llm(self, **_kwargs):
        self.last_kwargs = _kwargs
        message = Mock()
        message.get_text_content.return_value = self.content
        message.tool_calls = self.tool_calls
        return Mock(message=message)


class FakeModelManager:
    def __init__(self, model_instance: FakeModelInstance):
        self.model_instance = model_instance

    def get_model_instance(self, **_kwargs):
        return self.model_instance


def test_agent_model_requires_native_tool_call_feature() -> None:
    client = TenantAgentLLMClient(
        tenant_id="tenant-1",
        provider="provider-1",
        model="plain-model",
        model_manager=FakeModelManager(FakeModelInstance(features=[])),
    )

    with pytest.raises(ValueError, match="Function Calling"):
        client.validate_model_support()


def test_agent_model_accepts_single_or_multi_tool_call() -> None:
    for feature in (ModelFeature.TOOL_CALL, ModelFeature.MULTI_TOOL_CALL):
        client = TenantAgentLLMClient(
            tenant_id="tenant-1",
            provider="provider-1",
            model="tool-model",
            model_manager=FakeModelManager(FakeModelInstance(features=[feature])),
        )

        client.validate_model_support()


def test_agent_does_not_parse_tool_calls_from_assistant_text() -> None:
    model_instance = FakeModelInstance(
        features=[ModelFeature.TOOL_CALL],
        content='{"tool": "write_file", "arguments": {"path": "README.md", "content": "bad"}}',
    )
    client = TenantAgentLLMClient(
        tenant_id="tenant-1",
        provider="provider-1",
        model="tool-model",
        model_manager=FakeModelManager(model_instance),
    )

    step = client.next_step(messages=[], tools=[])

    assert step.tool_calls == []


def test_tenant_agent_llm_client_does_not_send_max_tokens() -> None:
    model_instance = FakeModelInstance(features=[ModelFeature.TOOL_CALL], content="ok")
    client = TenantAgentLLMClient(
        tenant_id="tenant-1",
        provider="provider-1",
        model="tool-model",
        model_manager=FakeModelManager(model_instance),
    )

    client.next_step(messages=[], tools=[])

    parameters = model_instance.last_kwargs["model_parameters"]
    assert "max_tokens" not in parameters


def test_tenant_agent_llm_client_strips_deepseek_reasoning_from_final_content() -> None:
    model_instance = FakeModelInstance(
        features=[ModelFeature.TOOL_CALL],
        content=(
            "<think>\n<!--dify-deepseek-reasoning-->"
            "Validation passed. The tool is complete.\n</think>"
            "已完成首个工具 image_to_image 的脚手架搭建与实现。"
        ),
    )
    client = TenantAgentLLMClient(
        tenant_id="tenant-1",
        provider="langgenius/deepseek/deepseek",
        model="deepseek-chat",
        model_manager=FakeModelManager(model_instance),
    )

    step = client.next_step(messages=[], tools=[])

    assert step.content == "已完成首个工具 image_to_image 的脚手架搭建与实现。"


def test_tenant_agent_llm_client_preserves_unmarked_think_tags_in_final_content() -> None:
    model_instance = FakeModelInstance(
        features=[ModelFeature.TOOL_CALL],
        content="请原样返回 <think>这是用户要求展示的文本</think>。",
    )
    client = TenantAgentLLMClient(
        tenant_id="tenant-1",
        provider="provider-1",
        model="tool-model",
        model_manager=FakeModelManager(model_instance),
    )

    step = client.next_step(messages=[], tools=[])

    assert step.content == "请原样返回 <think>这是用户要求展示的文本</think>。"


MIN_FILES = {
    "manifest.yaml": "version: 0.0.1\n",
    "main.py": "pass\n",
    "requirements.txt": "",
    "README.md": "# Demo\n",
    "provider/demo.yaml": "identity:\n  name: demo\n",
    "tools/echo.yaml": (
        "identity:\n  name: echo\n  author: acme\n  label:\n    en_US: Echo\n"
        "description:\n  human:\n    en_US: echo\n  llm: echo\n"
        "parameters:\n  - name: text\n    type: string\n    required: true\n"
    ),
    "tools/echo.py": (
        "from collections.abc import Generator\n"
        "from typing import Any\n"
        "from dify_plugin import Tool\n"
        "from dify_plugin.entities.tool import ToolInvokeMessage\n\n"
        "class EchoTool(Tool):\n"
        "    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:\n"
        "        yield self.create_text_message(tool_parameters.get('text', ''))\n"
    ),
}


def test_run_agent_turn_writes_file_without_installing() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                content="Updating invoke body",
                tool_calls=[
                    AgentToolCall(
                        id="1",
                        name="write_file",
                        arguments={
                            "path": "tools/echo.py",
                            "content": MIN_FILES["tools/echo.py"].replace(
                                "tool_parameters.get('text', '')",
                                "'ok'",
                            ),
                        },
                    )
                ],
            ),
            AgentLLMStep(content="Updated the echo tool."),
        ]
    )
    result = run_agent_turn(
        message="Make the tool always return ok",
        files=MIN_FILES,
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        tenant_id="tenant-1",
        user_id="user-1",
        llm_client=llm,
        has_published_version=True,
    )

    assert "yield self.create_text_message('ok')" in result.files["tools/echo.py"]
    assert result.dirty_installed is False
    assert result.plugin_unique_identifier is None
    assert result.installation_id is None
    assert result.preview_tool is not None
    assert result.preview_tool["tool_name"] == "echo"


def test_run_agent_turn_reports_validation_errors_without_installing() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="1",
                        name="write_file",
                        arguments={"path": "tools/echo.py", "content": "def broken(:\n"},
                    )
                ]
            ),
            AgentLLMStep(content="Tried to update."),
        ]
    )
    result = run_agent_turn(
        message="break it",
        files=MIN_FILES,
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        tenant_id="tenant-1",
        user_id="user-1",
        llm_client=llm,
    )

    assert result.dirty_installed is False
    assert result.validation_errors


def test_iter_agent_turn_emits_draft_tool_and_done_events() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                content="Updating file",
                tool_calls=[
                    AgentToolCall(
                        id="1",
                        name="write_file",
                        arguments={
                            "path": "README.md",
                            "content": "# Updated\n",
                        },
                    )
                ],
            ),
            AgentLLMStep(content="Done."),
        ]
    )
    events = list(
        iter_agent_turn(
            message="update readme",
            files=MIN_FILES,
            author="acme",
            plugin_name="demo",
            tool_name="echo",
            tenant_id="tenant-1",
            user_id="user-1",
            llm_client=llm,
        )
    )
    names = [event["event"] for event in events]
    assert "tool_call" in names
    assert "tool_result" in names
    assert "files" in names
    assert "done" in names
    assert events[-1]["event"] == "done"
    assert events[-1]["dirty_installed"] is False
    assert events[-1]["needs_reinstall"] is True
    assert "install" not in names

    tool_call_event = next(event for event in events if event["event"] == "tool_call")
    tool_result_event = next(event for event in events if event["event"] == "tool_result")
    assert tool_call_event["call_id"] == "1"
    assert tool_result_event["call_id"] == "1"
    assert tool_call_event["turn_id"] == tool_result_event["turn_id"]
    assert tool_call_event["event_id"] != tool_result_event["event_id"]


def test_bootstrap_thinking_events_are_temporary_and_share_call_id() -> None:
    class BootstrapLLM:
        def complete(self, prompt: str, on_event=None) -> dict[str, Any]:
            if on_event:
                on_event("分析工具结构")
            return {
                "provider_label": "Demo",
                "tool_label": "Echo",
                "tool_description": "echo text",
                "parameters": [],
                "credentials": [],
                "invoke_python_body": "yield self.create_text_message('ok')",
                "readme": "# Demo",
            }

    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="bootstrap-1",
                        name="bootstrap_scaffold",
                        arguments={"user_prompt": "echo"},
                    )
                ]
            ),
            AgentLLMStep(content="Created."),
        ]
    )
    checkpoints: list[dict[str, Any]] = []

    events = list(
        iter_agent_turn(
            message="create",
            files={},
            author="acme",
            plugin_name="demo",
            tool_name="echo",
            tenant_id="tenant-1",
            user_id="user-1",
            llm_client=llm,
            bootstrap_llm=BootstrapLLM(),
            on_checkpoint=checkpoints.append,
        )
    )

    thinking = [event for event in events if event["event"] == "thinking"]
    tool_result = next(event for event in events if event["event"] == "tool_result")
    assert thinking[0]["call_id"] == "bootstrap-1"
    assert thinking[0]["delta"] == "分析工具结构"
    assert thinking[-1]["done"] is True
    assert thinking[-1]["call_id"] == tool_result["call_id"]
    assert all("thinking" not in message.get("content", "") for message in events[-1]["messages"])
    assert all("thinking" not in message.get("content", "") for message in checkpoints[0]["messages"])


def test_bootstrap_thinking_is_yielded_before_tool_finishes() -> None:
    callback_seen = Event()
    release = Event()

    class BlockingBootstrapLLM:
        def complete(self, prompt: str, on_event=None) -> dict[str, Any]:
            if on_event:
                on_event("streamed")
            callback_seen.set()
            release.wait(timeout=2)
            return {
                "provider_label": "Demo",
                "tool_label": "Echo",
                "tool_description": "echo text",
                "parameters": [],
                "credentials": [],
                "invoke_python_body": "yield self.create_text_message('ok')",
            }

    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="bootstrap-1",
                        name="bootstrap_scaffold",
                        arguments={"user_prompt": "echo"},
                    )
                ]
            )
        ]
    )
    stream = iter(
        iter_agent_turn(
            message="create",
            files={},
            author="acme",
            plugin_name="demo",
            tool_name="echo",
            tenant_id="tenant-1",
            user_id="user-1",
            llm_client=llm,
            bootstrap_llm=BlockingBootstrapLLM(),
        )
    )
    next(stream)
    next(stream)
    next(stream)
    next(stream)
    observed: dict[str, Any] = {}
    consumer = Thread(target=lambda: observed.setdefault("event", next(stream)), daemon=True)
    consumer.start()
    assert callback_seen.wait(timeout=1)
    consumer.join(timeout=1)
    assert observed["event"]["event"] == "thinking"
    release.set()
    list(stream)


def test_bootstrap_cancellation_stops_waiting_for_provider() -> None:
    started = Event()
    cancelled = Event()
    release = Event()

    class BlockingBootstrapLLM:
        def complete(self, prompt: str, on_event=None) -> dict[str, Any]:
            started.set()
            release.wait(timeout=2)
            return {
                "provider_label": "Demo",
                "tool_label": "Echo",
                "tool_description": "echo text",
                "parameters": [],
                "credentials": [],
                "invoke_python_body": "yield self.create_text_message('ok')",
            }

    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="bootstrap-1",
                        name="bootstrap_scaffold",
                        arguments={"user_prompt": "echo"},
                    )
                ]
            )
        ]
    )
    stream = iter(
        iter_agent_turn(
            message="create",
            files={},
            author="acme",
            plugin_name="demo",
            tool_name="echo",
            tenant_id="tenant-1",
            user_id="user-1",
            llm_client=llm,
            bootstrap_llm=BlockingBootstrapLLM(),
            is_cancelled=cancelled.is_set,
        )
    )
    for _ in range(4):
        next(stream)
    observed: dict[str, Any] = {}
    consumer = Thread(target=lambda: observed.setdefault("event", next(stream)), daemon=True)
    consumer.start()
    assert started.wait(timeout=1)
    cancelled.set()
    consumer.join(timeout=0.5)
    stopped_waiting = not consumer.is_alive()
    release.set()
    consumer.join(timeout=2)

    assert stopped_waiting is True
    assert observed["event"]["event"] == "thinking"
    assert observed["event"]["done"] is True
    remaining = list(stream)
    assert any(event["event"] == "cancelled" for event in remaining)


def test_tool_specs_are_the_single_source_for_schemas_and_handlers() -> None:
    specs = tool_specs()
    schemas = tool_schemas()

    assert [spec.name for spec in specs] == [schema["name"] for schema in schemas]
    assert all(spec.parameters is schema["parameters"] for spec, schema in zip(specs, schemas, strict=True))
    assert all(callable(spec.handler) for spec in specs)


def test_iter_agent_turn_checkpoints_after_file_mutation() -> None:
    checkpoints: list[dict[str, Any]] = []
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="1",
                        name="write_file",
                        arguments={"path": "README.md", "content": "# Checkpointed\n"},
                    )
                ]
            ),
            AgentLLMStep(content="Done."),
        ]
    )

    events = list(
        iter_agent_turn(
            message="update readme",
            files=MIN_FILES,
            author="acme",
            plugin_name="demo",
            tool_name="echo",
            tenant_id="tenant-1",
            user_id="user-1",
            llm_client=llm,
            on_checkpoint=checkpoints.append,
        )
    )

    assert len(checkpoints) == 1
    checkpoint = checkpoints[0]
    assert checkpoint["files"]["README.md"] == "# Checkpointed\n"
    assert checkpoint["preview_tool"] is not None
    assert checkpoint["messages"][-1]["tool_calls"][0]["id"] == "1"
    file_event = next(event for event in events if event["event"] == "files")
    assert file_event["messages"] == checkpoint["messages"]


def test_iter_agent_turn_stops_when_checkpoint_fails() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="1",
                        name="write_file",
                        arguments={"path": "README.md", "content": "# Checkpointed\n"},
                    )
                ]
            )
        ]
    )

    def fail_checkpoint(_state: dict[str, Any]) -> int:
        raise RuntimeError("database unavailable")

    with pytest.raises(AgentCheckpointError, match="checkpoint"):
        list(
            iter_agent_turn(
                message="update readme",
                files=MIN_FILES,
                author="acme",
                plugin_name="demo",
                tool_name="echo",
                tenant_id="tenant-1",
                user_id="user-1",
                llm_client=llm,
                on_checkpoint=fail_checkpoint,
            )
        )


def test_agent_tool_schemas_do_not_expose_install_test_or_credentials() -> None:
    schemas = tool_schemas()

    assert {schema["name"] for schema in schemas}.isdisjoint({"install", "test", "verify_cycle"})
    credential_properties = [
        (schema["name"], schema["parameters"]["properties"]["credentials"])
        for schema in schemas
        if "credentials" in schema["parameters"].get("properties", {})
    ]
    assert credential_properties == [("add_tool", {"type": "array"})]


def test_agent_tool_schemas_always_declare_required_properties() -> None:
    schemas = tool_schemas()

    assert all(isinstance(schema["parameters"].get("required"), list) for schema in schemas)


def test_agent_stops_before_tool_call_budget_is_exceeded() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(id="1", name="list_files", arguments={}),
                    AgentToolCall(id="2", name="list_files", arguments={}),
                ]
            )
        ]
    )

    with pytest.raises(AgentBudgetExceededError, match="max_tool_calls"):
        list(
            iter_agent_turn(
                message="list",
                files=MIN_FILES,
                author="acme",
                plugin_name="demo",
                tool_name="echo",
                tenant_id="tenant-1",
                user_id="user-1",
                llm_client=llm,
                limits=AgentTurnLimits(max_tool_calls=1),
            )
        )


def test_agent_rejects_oversized_file_and_restores_draft() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                tool_calls=[
                    AgentToolCall(
                        id="1",
                        name="write_file",
                        arguments={"path": "README.md", "content": "x" * 100},
                    )
                ]
            )
        ]
    )

    with pytest.raises(AgentBudgetExceededError, match="max_single_file_bytes"):
        list(
            iter_agent_turn(
                message="write",
                files=MIN_FILES,
                author="acme",
                plugin_name="demo",
                tool_name="echo",
                tenant_id="tenant-1",
                user_id="user-1",
                llm_client=llm,
                limits=AgentTurnLimits(max_single_file_bytes=20),
            )
        )


def test_agent_breaks_on_repeated_identical_tool_calls() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(tool_calls=[AgentToolCall(id="1", name="list_files", arguments={})]),
            AgentLLMStep(tool_calls=[AgentToolCall(id="2", name="list_files", arguments={})]),
            AgentLLMStep(tool_calls=[AgentToolCall(id="3", name="list_files", arguments={})]),
            AgentLLMStep(tool_calls=[AgentToolCall(id="4", name="list_files", arguments={})]),
        ]
    )

    with pytest.raises(AgentBudgetExceededError, match="repeated_tool_call"):
        list(
            iter_agent_turn(
                message="repeat",
                files=MIN_FILES,
                author="acme",
                plugin_name="demo",
                tool_name="echo",
                tenant_id="tenant-1",
                user_id="user-1",
                llm_client=llm,
                limits=AgentTurnLimits(max_repeated_tool_calls=3),
            )
        )


def test_hydrate_history_messages_replays_tool_calls() -> None:
    messages = hydrate_history_messages(
        [
            {"role": "user", "content": "update echo"},
            {
                "role": "assistant",
                "content": "writing",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "write_file",
                        "arguments": {"path": "tools/echo.py", "content": "x" * 500},
                        "result": '{"ok": true, "path": "tools/echo.py"}',
                    },
                    {
                        "id": "c2",
                        "name": "validate",
                        "arguments": {},
                        "result": '{"ok": true}',
                    },
                ],
            },
        ]
    )
    assert any(isinstance(item, ToolPromptMessage) for item in messages)
    tool_msgs = [item for item in messages if isinstance(item, ToolPromptMessage)]
    assert len(tool_msgs) == 2
    assert tool_msgs[0].tool_call_id == "c1"


def test_run_agent_turn_sees_prior_tool_history() -> None:
    llm = ScriptedLLM(steps=[AgentLLMStep(content="Already validated previously.")])
    history = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "v1",
                    "name": "validate",
                    "arguments": {},
                    "result": '{"ok": false, "errors": ["bad yaml"]}',
                }
            ],
        }
    ]
    result = run_agent_turn(
        message="continue",
        files=MIN_FILES,
        author="acme",
        plugin_name="demo",
        tool_name="echo",
        tenant_id="tenant-1",
        user_id="user-1",
        llm_client=llm,
        history=history,
    )
    assert result.messages[-1]["content"] == "Already validated previously."
    first_call_messages = llm.calls[0]["messages"]
    assert any(isinstance(item, ToolPromptMessage) for item in first_call_messages)


def test_iter_agent_turn_honours_cancel_flag() -> None:
    llm = ScriptedLLM(
        steps=[
            AgentLLMStep(
                content="should not finish",
                tool_calls=[AgentToolCall(id="1", name="list_files", arguments={})],
            )
        ]
    )
    events = list(
        iter_agent_turn(
            message="stop soon",
            files=MIN_FILES,
            author="acme",
            plugin_name="demo",
            tool_name="echo",
            tenant_id="tenant-1",
            user_id="user-1",
            llm_client=llm,
            is_cancelled=lambda: True,
        )
    )
    assert any(event["event"] == "cancelled" for event in events)
    assert events[-1]["event"] == "done"
    assert events[-1]["cancelled"] is True
