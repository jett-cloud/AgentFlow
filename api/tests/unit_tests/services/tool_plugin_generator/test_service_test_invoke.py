from types import SimpleNamespace
from unittest.mock import Mock

from core.app.entities.app_invoke_entities import InvokeFrom
from core.tools.__base.tool_runtime import ToolRuntime
from core.tools.entities.tool_entities import (
    ToolInvokeFrom,
    ToolInvokeMessage,
    ToolParameter,
    ToolProviderType,
)
from core.tools.errors import ToolProviderNotFoundError
from services.tool_plugin_generator import service


def test_test_tool_plugin_normalizes_two_segment_provider_id(monkeypatch) -> None:
    runtime = Mock()
    runtime.invoke.return_value = iter([])
    get_tool_runtime = Mock(side_effect=[ToolProviderNotFoundError("no"), runtime])
    monkeypatch.setattr(service.ToolManager, "get_tool_runtime", get_tool_runtime)
    monkeypatch.setattr(service.db, "session", Mock(return_value=object()))
    monkeypatch.setattr(service.time, "monotonic", Mock(side_effect=[1.0, 1.01]))

    service.test_tool_plugin(
        tenant_id="tenant-1",
        user_id="user-1",
        provider_id="ghy/doubao_image_tools",
        tool_name="generate_image",
        parameters={},
        credentials=None,
        allow_workspace_credentials=True,
    )

    assert get_tool_runtime.call_args_list[0].kwargs["provider_id"] == (
        "ghy/doubao_image_tools/doubao_image_tools"
    )


def test_test_tool_plugin_invokes_installed_plugin_and_returns_text(monkeypatch) -> None:
    session = object()
    runtime = Mock()
    runtime.plugin_unique_identifier = "acme/echo_plugin:0.0.1@abc"
    runtime.invoke.return_value = iter(
        [
            ToolInvokeMessage(
                type=ToolInvokeMessage.MessageType.TEXT,
                message=ToolInvokeMessage.TextMessage(text="echo: hello"),
            )
        ]
    )
    get_tool_runtime = Mock(side_effect=ToolProviderNotFoundError("no creds"))
    # BUILT_IN fails → PLUGIN fallback
    plugin_runtime = runtime
    get_tool_runtime.side_effect = [
        ToolProviderNotFoundError("no creds"),
        plugin_runtime,
    ]
    monkeypatch.setattr(service.ToolManager, "get_tool_runtime", get_tool_runtime)
    monkeypatch.setattr(service.db, "session", Mock(return_value=session))
    monotonic = Mock(side_effect=[10.0, 10.125])
    monkeypatch.setattr(service.time, "monotonic", monotonic)

    result = service.test_tool_plugin(
        tenant_id="tenant-1",
        user_id="user-1",
        provider_id="acme/echo_plugin",
        tool_name="echo",
        parameters={"text": "hello"},
        credentials=None,
        allow_workspace_credentials=True,
    )

    assert get_tool_runtime.call_count == 2
    assert get_tool_runtime.call_args_list[0].kwargs["provider_type"] == ToolProviderType.BUILT_IN
    assert get_tool_runtime.call_args_list[1].kwargs["provider_type"] == ToolProviderType.PLUGIN
    runtime.invoke.assert_called_once_with(
        session=session,
        user_id="user-1",
        tool_parameters={"text": "hello"},
    )
    assert result.ok is True
    assert result.output_text == "echo: hello"
    assert result.error is None
    assert result.elapsed_ms == 125
    assert result.plugin_unique_identifier == "acme/echo_plugin:0.0.1@abc"


def test_test_tool_plugin_forks_runtime_with_inline_credentials(monkeypatch) -> None:
    session = object()
    forked = Mock()
    forked.invoke.return_value = iter(
        [
            ToolInvokeMessage(
                type=ToolInvokeMessage.MessageType.TEXT,
                message=ToolInvokeMessage.TextMessage(text="ok"),
            )
        ]
    )
    plugin_tool = Mock()
    plugin_tool.fork_tool_runtime.return_value = forked
    get_tool_runtime = Mock(return_value=plugin_tool)
    monkeypatch.setattr(service.ToolManager, "get_tool_runtime", get_tool_runtime)
    monkeypatch.setattr(service.db, "session", Mock(return_value=session))
    monkeypatch.setattr(service.time, "monotonic", Mock(side_effect=[1.0, 1.05]))

    result = service.test_tool_plugin(
        tenant_id="tenant-1",
        user_id="user-1",
        provider_id="acme/image",
        tool_name="generate_image",
        parameters={"prompt": "cat"},
        credentials={"api_key": "sk-test"},
        allow_workspace_credentials=False,
    )

    get_tool_runtime.assert_called_once_with(
        provider_type=ToolProviderType.PLUGIN,
        provider_id="acme/image/image",
        tool_name="generate_image",
        tenant_id="tenant-1",
        user_id="user-1",
        invoke_from=InvokeFrom.DEBUGGER,
        tool_invoke_from=ToolInvokeFrom.WORKFLOW,
    )
    runtime_arg = plugin_tool.fork_tool_runtime.call_args.args[0]
    assert isinstance(runtime_arg, ToolRuntime)
    assert runtime_arg.credentials == {"api_key": "sk-test"}
    forked.invoke.assert_called_once()
    assert result.ok is True
    assert result.output_text == "ok"


def test_interpret_tool_test_messages_marks_request_failed_text_as_error() -> None:
    messages = [
        ToolInvokeMessage(
            type=ToolInvokeMessage.MessageType.TEXT,
            message=ToolInvokeMessage.TextMessage(text="Request failed: 'Session' object has no attribute 'post'"),
        )
    ]
    ok, error = service.interpret_tool_test_messages(
        messages,
        output_text="Request failed: 'Session' object has no attribute 'post'",
    )
    assert ok is False
    assert error
    assert error.startswith("Request failed:")


def test_interpret_tool_test_messages_keeps_plain_text_success() -> None:
    messages = [
        ToolInvokeMessage(
            type=ToolInvokeMessage.MessageType.TEXT,
            message=ToolInvokeMessage.TextMessage(text="hello"),
        )
    ]
    ok, error = service.interpret_tool_test_messages(messages, output_text="hello")
    assert ok is True
    assert error is None


def test_interpret_tool_test_messages_accepts_blob_as_success() -> None:
    messages = [
        ToolInvokeMessage(
            type=ToolInvokeMessage.MessageType.BLOB,
            message=ToolInvokeMessage.BlobMessage(blob=b"png"),
            meta={"mime_type": "image/png"},
        )
    ]
    ok, error = service.interpret_tool_test_messages(messages, output_text="")
    assert ok is True
    assert error is None


def test_hydrate_tool_file_parameters_builds_file_objects(monkeypatch) -> None:
    file_obj = object()
    build = Mock(return_value=file_obj)
    monkeypatch.setattr(service, "build_from_mapping", build)

    runtime = SimpleNamespace(
        entity=SimpleNamespace(
            parameters=[
                SimpleNamespace(name="image_file", type=ToolParameter.ToolParameterType.FILE),
                SimpleNamespace(name="size", type=ToolParameter.ToolParameterType.STRING),
            ]
        )
    )
    mapping = {
        "type": "image",
        "transfer_method": "local_file",
        "upload_file_id": "11111111-1111-1111-1111-111111111111",
        "url": "",
    }
    hydrated = service.hydrate_tool_file_parameters(
        runtime=runtime,
        tenant_id="tenant-1",
        parameters={"image_file": mapping, "size": "auto"},
    )

    assert hydrated["image_file"] is file_obj
    assert hydrated["size"] == "auto"
    build.assert_called_once()
    assert build.call_args.kwargs["tenant_id"] == "tenant-1"
    assert build.call_args.kwargs["mapping"] == mapping


def test_test_tool_plugin_hydrates_file_parameters_before_invoke(monkeypatch) -> None:
    session = object()
    file_obj = object()
    runtime = Mock()
    runtime.entity = SimpleNamespace(
        parameters=[SimpleNamespace(name="image_file", type=ToolParameter.ToolParameterType.FILE)]
    )
    runtime.invoke.return_value = iter(
        [
            ToolInvokeMessage(
                type=ToolInvokeMessage.MessageType.TEXT,
                message=ToolInvokeMessage.TextMessage(text="done"),
            )
        ]
    )
    get_tool_runtime = Mock(side_effect=[ToolProviderNotFoundError("no"), runtime])
    monkeypatch.setattr(service.ToolManager, "get_tool_runtime", get_tool_runtime)
    monkeypatch.setattr(service.db, "session", Mock(return_value=session))
    monkeypatch.setattr(service.time, "monotonic", Mock(side_effect=[1.0, 1.2]))
    monkeypatch.setattr(service, "build_from_mapping", Mock(return_value=file_obj))

    mapping = {
        "type": "image",
        "transfer_method": "local_file",
        "upload_file_id": "11111111-1111-1111-1111-111111111111",
        "url": "",
    }
    result = service.test_tool_plugin(
        tenant_id="tenant-1",
        user_id="user-1",
        provider_id="ghy/remove-bg/remove-bg",
        tool_name="remove_image_background",
        parameters={"image_file": mapping, "size": "auto"},
        credentials=None,
        allow_workspace_credentials=True,
    )

    runtime.invoke.assert_called_once_with(
        session=session,
        user_id="user-1",
        tool_parameters={"image_file": file_obj, "size": "auto"},
    )
    assert result.ok is True
    assert result.output_text == "done"
