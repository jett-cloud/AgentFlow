"""tools."""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast, override

from sqlalchemy.orm import Session, sessionmaker

from core.app.entities.app_invoke_entities import DifyRunContext
from core.callback_handler.workflow_tool_callback_handler import DifyWorkflowCallbackHandler
from core.db.session_factory import session_factory
from core.helper.trace_id_helper import ParentTraceContext
from core.plugin.impl.exc import PluginDaemonClientSideError, PluginInvokeError
from core.plugin.impl.plugin import PluginInstaller
from core.tools.entities.tool_entities import ToolProviderType as CoreToolProviderType
from core.tools.errors import ToolInvokeError
from core.tools.tool_engine import ToolEngine
from core.tools.tool_manager import ToolManager
from core.tools.utils.message_transformer import ToolFileMessageTransformer
from core.workflow.runtime.variables.system_variables import SystemVariableKey, get_system_text
from graphon.model_runtime.entities.llm_entities import (
    LLMUsage,
)
from graphon.nodes.protocols import FileReferenceFactoryProtocol
from graphon.nodes.runtime import ToolNodeRuntimeProtocol
from graphon.nodes.tool.exc import ToolNodeError, ToolRuntimeInvocationError, ToolRuntimeResolutionError
from graphon.nodes.tool_runtime_entities import (
    ToolRuntimeHandle,
    ToolRuntimeMessage,
    ToolRuntimeParameter,
)
from services.tools.builtin_tools_manage_service import BuiltinToolManageService

if TYPE_CHECKING:
    from core.tools.__base.tool import Tool
    from core.tools.entities.tool_entities import ToolInvokeMessage as CoreToolInvokeMessage
    from graphon.nodes.tool.entities import ToolNodeData

from core.workflow.runtime.adapters.context import resolve_dify_run_context
from core.workflow.runtime.adapters.files import DifyFileReferenceFactory


@dataclass(frozen=True, slots=True)
class _WorkflowToolRuntimeSpec:
    provider_type: CoreToolProviderType
    provider_id: str
    tool_name: str
    tool_configurations: dict[str, Any]
    credential_id: str | None = None


@dataclass(frozen=True, slots=True)
class _WorkflowToolRuntimeBinding:
    """Workflow-private runtime state stored inside the opaque graph handle.

    The binding keeps conversation scope in `core.workflow` while `graphon`
    continues to treat the handle as an opaque token.
    """

    tool: Tool
    conversation_id: str | None = None
    parent_trace_context: ParentTraceContext | None = None
    trace_session_id: str | None = None


class DifyToolNodeRuntime(ToolNodeRuntimeProtocol):
    def __init__(
        self,
        run_context: Mapping[str, Any] | DifyRunContext,
        session_maker: sessionmaker[Session] | None = None,
    ) -> None:
        self._run_context = resolve_dify_run_context(run_context)
        self._file_reference_factory = DifyFileReferenceFactory(self._run_context)
        self._session_maker = session_maker

    @property
    def file_reference_factory(self) -> FileReferenceFactoryProtocol:
        return self._file_reference_factory

    @override
    def build_file_reference(self, *, mapping: Mapping[str, Any]):
        return self._file_reference_factory.build_from_mapping(mapping=mapping)

    @override
    def get_runtime(
        self,
        *,
        node_id: str,
        node_data: ToolNodeData,
        variable_pool,
        node_execution_id: str | None = None,
    ) -> ToolRuntimeHandle:
        try:
            tool_runtime = ToolManager.get_workflow_tool_runtime(
                self._run_context.tenant_id,
                self._run_context.app_id,
                node_id,
                self._build_tool_runtime_spec(node_data),
                self._run_context.user_id,
                self._run_context.invoke_from,
                variable_pool,
            )
        except ToolNodeError:
            raise
        except Exception as exc:
            raise ToolRuntimeResolutionError(str(exc)) from exc

        conversation_id = (
            None if variable_pool is None else get_system_text(variable_pool, SystemVariableKey.CONVERSATION_ID)
        )
        parent_trace_context: ParentTraceContext | None = None
        trace_session_id: str | None = None
        if self._is_workflow_tool_provider(node_data):
            outer_workflow_run_id = (
                None
                if variable_pool is None
                else get_system_text(variable_pool, SystemVariableKey.WORKFLOW_EXECUTION_ID)
            )
            if isinstance(outer_workflow_run_id, str) and isinstance(node_execution_id, str):
                parent_trace_context = ParentTraceContext(
                    parent_workflow_run_id=outer_workflow_run_id,
                    parent_node_execution_id=node_execution_id,
                )
            if isinstance(self._run_context.trace_session_id, str) and self._run_context.trace_session_id:
                trace_session_id = self._run_context.trace_session_id
        return ToolRuntimeHandle(
            raw=_WorkflowToolRuntimeBinding(
                tool=tool_runtime,
                conversation_id=conversation_id,
                parent_trace_context=parent_trace_context,
                trace_session_id=trace_session_id,
            )
        )

    @override
    def get_runtime_parameters(
        self,
        *,
        tool_runtime: ToolRuntimeHandle,
    ) -> Sequence[ToolRuntimeParameter]:
        tool = self._tool_from_handle(tool_runtime)
        return [
            ToolRuntimeParameter(name=parameter.name, required=parameter.required)
            for parameter in (tool.get_merged_runtime_parameters() or [])
        ]

    @override
    def invoke(
        self,
        *,
        tool_runtime: ToolRuntimeHandle,
        tool_parameters: Mapping[str, Any],
        workflow_call_depth: int,
        provider_name: str,
    ) -> Generator[ToolRuntimeMessage, None, None]:
        runtime_binding = self._binding_from_handle(tool_runtime)
        tool = runtime_binding.tool
        callback = DifyWorkflowCallbackHandler()
        if runtime_binding.parent_trace_context and hasattr(tool, "set_parent_trace_context"):
            tool.set_parent_trace_context(
                parent_workflow_run_id=runtime_binding.parent_trace_context.parent_workflow_run_id,
                parent_node_execution_id=runtime_binding.parent_trace_context.parent_node_execution_id,
            )
        elif hasattr(tool, "clear_parent_trace_context"):
            tool.clear_parent_trace_context()
        if runtime_binding.trace_session_id and hasattr(tool, "set_trace_session_id"):
            tool.set_trace_session_id(runtime_binding.trace_session_id)
        elif hasattr(tool, "clear_trace_session_id"):
            tool.clear_trace_session_id()

        try:
            session_maker = self._session_maker or session_factory.get_session_maker()
            with session_maker.begin() as session:
                messages = ToolEngine.generic_invoke(
                    session=session,
                    tool=tool,
                    tool_parameters=dict(tool_parameters),
                    user_id=self._run_context.user_id,
                    workflow_tool_callback=callback,
                    workflow_call_depth=workflow_call_depth,
                    app_id=self._run_context.app_id,
                    conversation_id=runtime_binding.conversation_id,
                )
                transformed_messages = ToolFileMessageTransformer.transform_tool_invoke_messages(
                    messages=messages,
                    user_id=self._run_context.user_id,
                    tenant_id=self._run_context.tenant_id,
                    conversation_id=runtime_binding.conversation_id,
                )
                yield from self._adapt_messages(transformed_messages, provider_name=provider_name)
        except Exception as exc:
            raise self._map_invocation_exception(exc, provider_name=provider_name) from exc

    @override
    def get_usage(
        self,
        *,
        tool_runtime: ToolRuntimeHandle,
    ) -> LLMUsage:
        latest = getattr(self._binding_from_handle(tool_runtime).tool, "latest_usage", None)
        if isinstance(latest, LLMUsage):
            return latest
        if isinstance(latest, dict):
            return LLMUsage.model_validate(latest)
        return LLMUsage.empty_usage()

    def resolve_provider_icons(
        self,
        *,
        provider_name: str,
        default_icon: str | None = None,
    ) -> tuple[str | Mapping[str, str] | None, str | Mapping[str, str] | None]:
        icon: str | Mapping[str, str] | None = default_icon
        icon_dark: str | Mapping[str, str] | None = None

        manager = PluginInstaller()
        plugins = manager.list_plugins(self._run_context.tenant_id)
        try:
            current_plugin = next(plugin for plugin in plugins if f"{plugin.plugin_id}/{plugin.name}" == provider_name)
            icon = current_plugin.declaration.icon
        except StopIteration:
            pass

        try:
            builtin_tool = next(
                provider
                for provider in BuiltinToolManageService.list_builtin_tools(
                    self._run_context.user_id,
                    self._run_context.tenant_id,
                )
                if provider.name == provider_name
            )
            icon = builtin_tool.icon
            icon_dark = builtin_tool.icon_dark
        except StopIteration:
            pass

        return icon, icon_dark

    @staticmethod
    def _tool_from_handle(tool_runtime: ToolRuntimeHandle) -> Tool:
        return DifyToolNodeRuntime._binding_from_handle(tool_runtime).tool

    @staticmethod
    def _binding_from_handle(tool_runtime: ToolRuntimeHandle) -> _WorkflowToolRuntimeBinding:
        if isinstance(tool_runtime.raw, _WorkflowToolRuntimeBinding):
            return tool_runtime.raw
        return _WorkflowToolRuntimeBinding(tool=cast("Tool", tool_runtime.raw))

    @staticmethod
    def _build_tool_runtime_spec(node_data: ToolNodeData) -> _WorkflowToolRuntimeSpec:
        tool_configurations = dict(node_data.tool_configurations)
        tool_configurations.update(
            {name: tool_input.model_dump(mode="python") for name, tool_input in node_data.tool_parameters.items()}
        )
        return _WorkflowToolRuntimeSpec(
            provider_type=CoreToolProviderType(node_data.provider_type.value),
            provider_id=node_data.provider_id,
            tool_name=node_data.tool_name,
            tool_configurations=tool_configurations,
            credential_id=node_data.credential_id,
        )

    @staticmethod
    def _is_workflow_tool_provider(node_data: ToolNodeData) -> bool:
        return node_data.provider_type.value == CoreToolProviderType.WORKFLOW.value

    def _adapt_messages(
        self,
        messages: Generator[CoreToolInvokeMessage, None, None],
        *,
        provider_name: str,
    ) -> Generator[ToolRuntimeMessage, None, None]:
        try:
            for message in messages:
                yield self._convert_message(message)
        except Exception as exc:
            raise self._map_invocation_exception(exc, provider_name=provider_name) from exc

    def _convert_message(self, message: CoreToolInvokeMessage) -> ToolRuntimeMessage:
        graph_message_type = ToolRuntimeMessage.MessageType(message.type.value)
        graph_message = self._convert_message_payload(message.message)
        graph_meta = message.meta.copy() if message.meta is not None else None
        return ToolRuntimeMessage(type=graph_message_type, message=graph_message, meta=graph_meta)

    def _convert_message_payload(
        self,
        message: CoreToolInvokeMessage.TextMessage
        | CoreToolInvokeMessage.JsonMessage
        | CoreToolInvokeMessage.BlobChunkMessage
        | CoreToolInvokeMessage.BlobMessage
        | CoreToolInvokeMessage.LogMessage
        | CoreToolInvokeMessage.FileMessage
        | CoreToolInvokeMessage.VariableMessage
        | CoreToolInvokeMessage.RetrieverResourceMessage
        | None,
    ) -> (
        ToolRuntimeMessage.TextMessage
        | ToolRuntimeMessage.JsonMessage
        | ToolRuntimeMessage.BlobChunkMessage
        | ToolRuntimeMessage.BlobMessage
        | ToolRuntimeMessage.LogMessage
        | ToolRuntimeMessage.FileMessage
        | ToolRuntimeMessage.VariableMessage
        | ToolRuntimeMessage.RetrieverResourceMessage
        | None
    ):
        if message is None:
            return None

        from core.tools.entities.tool_entities import ToolInvokeMessage as CoreToolInvokeMessage

        match message:
            case CoreToolInvokeMessage.TextMessage():
                return ToolRuntimeMessage.TextMessage(text=message.text)
            case CoreToolInvokeMessage.JsonMessage():
                return ToolRuntimeMessage.JsonMessage(
                    json_object=message.json_object,
                    suppress_output=message.suppress_output,
                )
            case CoreToolInvokeMessage.BlobMessage():
                return ToolRuntimeMessage.BlobMessage(blob=message.blob)
            case CoreToolInvokeMessage.BlobChunkMessage():
                return ToolRuntimeMessage.BlobChunkMessage(
                    id=message.id,
                    sequence=message.sequence,
                    total_length=message.total_length,
                    blob=message.blob,
                    end=message.end,
                )
            case CoreToolInvokeMessage.FileMessage():
                return ToolRuntimeMessage.FileMessage(file_marker=message.file_marker)
            case CoreToolInvokeMessage.VariableMessage():
                return ToolRuntimeMessage.VariableMessage(
                    variable_name=message.variable_name,
                    variable_value=message.variable_value,
                    stream=message.stream,
                )
            case CoreToolInvokeMessage.LogMessage():
                return ToolRuntimeMessage.LogMessage(
                    id=message.id,
                    label=message.label,
                    parent_id=message.parent_id,
                    error=message.error,
                    status=ToolRuntimeMessage.LogMessage.LogStatus(message.status.value),
                    data=dict(message.data),
                    metadata=dict(message.metadata),
                )
            case CoreToolInvokeMessage.RetrieverResourceMessage():
                retriever_resources = [
                    resource.model_dump() if hasattr(resource, "model_dump") else dict(resource)
                    for resource in message.retriever_resources
                ]
                return ToolRuntimeMessage.RetrieverResourceMessage(
                    retriever_resources=retriever_resources,
                    context=message.context,
                )
            case _:
                raise TypeError(f"unsupported tool message payload: {type(message).__name__}")

    @staticmethod
    def _map_invocation_exception(exc: Exception, *, provider_name: str) -> ToolNodeError:
        match exc:
            case ToolNodeError():
                return exc
            case PluginInvokeError():
                return ToolRuntimeInvocationError(exc.to_user_friendly_error(plugin_name=provider_name))
            case PluginDaemonClientSideError():
                return ToolRuntimeInvocationError(f"Failed to invoke tool, error: {exc.description}")
            case ToolInvokeError():
                return ToolRuntimeInvocationError(f"Failed to invoke tool {provider_name}: {exc}")
            case _:
                return ToolRuntimeInvocationError(str(exc))
