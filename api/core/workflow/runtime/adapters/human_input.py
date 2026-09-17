"""human input."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.app.entities.app_invoke_entities import DifyRunContext
from core.repositories.human_input_repository import (
    FormCreateParams,
    HumanInputFormEntity,
    HumanInputFormRepository,
    HumanInputFormRepositoryImpl,
)
from core.workflow.graph.adapters.human_input_adapter import (
    BoundRecipient,
    DeliveryChannelConfig,
    DeliveryMethodType,
    EmailDeliveryMethod,
    EmailRecipients,
    is_human_input_webapp_enabled,
    parse_human_input_delivery_methods,
)
from core.workflow.nodes.human_input.entities import (
    FileInputConfig,
    FileListInputConfig,
    FormInputConfig,
    HumanInputNodeData,
)

if TYPE_CHECKING:
    pass

from core.workflow.runtime.adapters.context import resolve_dify_run_context
from core.workflow.runtime.adapters.files import DifyFileReferenceFactory


def apply_dify_debug_email_recipient(
    method: DeliveryChannelConfig,
    *,
    enabled: bool,
    actor_id: str | None,
) -> DeliveryChannelConfig:
    """Apply the Dify debugger-specific email recipient override outside `graphon`."""
    if not enabled:
        return method
    if not isinstance(method, EmailDeliveryMethod):
        return method
    if not method.config.debug_mode:
        return method

    if actor_id is None:
        debug_recipients = EmailRecipients(include_bound_group=False, items=[])
    else:
        debug_recipients = EmailRecipients(
            include_bound_group=False,
            items=[BoundRecipient(reference_id=actor_id)],
        )
    debug_config = method.config.with_recipients(debug_recipients)
    return method.model_copy(update={"config": debug_config})


class DifyHumanInputNodeRuntime:
    def __init__(
        self,
        run_context: Mapping[str, Any] | DifyRunContext,
        *,
        workflow_execution_id_getter: Callable[[], str | None] | None = None,
        conversation_id_getter: Callable[[], str | None] | None = None,
        form_repository: HumanInputFormRepository | None = None,
    ) -> None:
        self._run_context = resolve_dify_run_context(run_context)
        self._workflow_execution_id_getter = workflow_execution_id_getter
        self._conversation_id_getter = conversation_id_getter
        self._form_repository = form_repository
        self._file_reference_factory = DifyFileReferenceFactory(self._run_context)

    def _invoke_source(self) -> str:
        invoke_from = self._run_context.invoke_from
        if isinstance(invoke_from, str):
            return invoke_from
        if isinstance(invoke_from, Enum):
            return str(invoke_from.value)
        return str(invoke_from)

    def _resolve_delivery_methods(self, *, node_data: HumanInputNodeData) -> Sequence[DeliveryChannelConfig]:
        invoke_source = self._invoke_source()
        methods = [method for method in parse_human_input_delivery_methods(node_data) if method.enabled]
        if invoke_source in {"debugger", "explore"}:
            methods = [method for method in methods if method.type != DeliveryMethodType.WEBAPP]
        return [
            apply_dify_debug_email_recipient(
                method,
                enabled=invoke_source == "debugger",
                actor_id=self._run_context.user_id,
            )
            for method in methods
        ]

    def _display_in_ui(self, *, node_data: HumanInputNodeData) -> bool:
        if self._invoke_source() == "debugger":
            return True
        return is_human_input_webapp_enabled(node_data)

    def build_form_repository(self) -> HumanInputFormRepository:
        if self._form_repository is not None:
            return self._form_repository

        return self._build_form_repository()

    def _build_form_repository(self) -> HumanInputFormRepository:
        invoke_source = self._invoke_source()
        return HumanInputFormRepositoryImpl(
            tenant_id=self._run_context.tenant_id,
            app_id=self._run_context.app_id,
            workflow_execution_id=self._workflow_execution_id_getter() if self._workflow_execution_id_getter else None,
            invoke_source=invoke_source,
            submission_actor_id=self._run_context.user_id if invoke_source in {"debugger", "explore"} else None,
        )

    def with_form_repository(self, form_repository: HumanInputFormRepository) -> DifyHumanInputNodeRuntime:
        return DifyHumanInputNodeRuntime(
            self._run_context,
            workflow_execution_id_getter=self._workflow_execution_id_getter,
            conversation_id_getter=self._conversation_id_getter,
            form_repository=form_repository,
        )

    def get_form(self, *, node_id: str) -> HumanInputFormEntity | None:
        repo = self.build_form_repository()
        return repo.get_form(node_id)

    def restore_submitted_data(
        self,
        *,
        node_data: HumanInputNodeData,
        submitted_data: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        restored_data: dict[str, Any] = dict(submitted_data)
        for input_config in node_data.inputs:
            output_variable_name = input_config.output_variable_name
            if output_variable_name not in submitted_data:
                continue
            restored_data[output_variable_name] = self._restore_submitted_value(
                input_config=input_config,
                value=submitted_data[output_variable_name],
            )
        return restored_data

    def create_form(
        self,
        *,
        node_id: str,
        node_data: HumanInputNodeData,
        rendered_content: str,
        resolved_default_values: Mapping[str, Any],
    ) -> HumanInputFormEntity:
        repo = self.build_form_repository()
        params = FormCreateParams(
            workflow_execution_id=self._workflow_execution_id_getter() if self._workflow_execution_id_getter else None,
            # A chatflow (advanced-chat) run carries a conversation; tag the form with
            # it too so it is queryable per conversation. None for a pure workflow run.
            conversation_id=self._conversation_id_getter() if self._conversation_id_getter else None,
            node_id=node_id,
            form_config=node_data,
            rendered_content=rendered_content,
            delivery_methods=self._resolve_delivery_methods(node_data=node_data),
            display_in_ui=self._display_in_ui(node_data=node_data),
            resolved_default_values=resolved_default_values,
        )
        return repo.create_form(params)

    def _restore_submitted_value(
        self,
        *,
        input_config: FormInputConfig,
        value: Any,
    ) -> Any:
        if isinstance(input_config, FileInputConfig):
            return self._restore_submitted_file_value(
                output_variable_name=input_config.output_variable_name,
                value=value,
            )
        if isinstance(input_config, FileListInputConfig):
            return self._restore_submitted_file_list_value(
                output_variable_name=input_config.output_variable_name,
                value=value,
            )
        return value

    def _restore_submitted_file_value(
        self,
        *,
        output_variable_name: str,
        value: Any,
    ) -> Any:
        if not isinstance(value, Mapping):
            msg = (
                "HumanInput file submission must be persisted as a mapping, "
                f"output_variable_name={output_variable_name}"
            )
            raise ValueError(msg)
        return self._file_reference_factory.build_from_mapping(mapping=value)

    def _restore_submitted_file_list_value(
        self,
        *,
        output_variable_name: str,
        value: Any,
    ) -> list[Any]:
        if not isinstance(value, list):
            msg = (
                "HumanInput file-list submission must be persisted as a list, "
                f"output_variable_name={output_variable_name}"
            )
            raise ValueError(msg)
        if any(not isinstance(item, Mapping) for item in value):
            msg = f"HumanInput file-list submission must contain mappings, output_variable_name={output_variable_name}"
            raise ValueError(msg)
        return [self._file_reference_factory.build_from_mapping(mapping=item) for item in value]
