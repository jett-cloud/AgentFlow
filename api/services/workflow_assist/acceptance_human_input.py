"""In-memory Human Input forms for Workflow Assist pause/resume verification."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.repositories.human_input_repository import FormCreateParams
from core.workflow.nodes.human_input.entities import (
    FileInputConfig,
    FileListInputConfig,
    ParagraphInputConfig,
    SelectInputConfig,
)
from core.workflow.nodes.human_input.enums import HumanInputFormStatus, ValueSourceType
from libs.datetime_utils import naive_utc_now


class UnsupportedHumanInputFixtureError(ValueError):
    """Raised when a safe in-memory form value cannot be constructed."""


@dataclass
class AcceptanceHumanInputForm:
    id: str
    rendered_content: str
    created_at: datetime
    expiration_time: datetime
    form_config: object
    resolved_default_values: dict[str, Any]
    submission_token: str | None = None
    recipients: list[object] = field(default_factory=list)
    selected_action_id: str | None = None
    submitted_data: dict[str, Any] | None = None
    status: HumanInputFormStatus = HumanInputFormStatus.WAITING

    @property
    def submitted(self) -> bool:
        return self.status == HumanInputFormStatus.SUBMITTED


class AcceptanceHumanInputFormRepository:
    """Cloneable repository used only by the non-persisting Assist executor."""

    def __init__(self) -> None:
        self._forms_by_id: dict[str, AcceptanceHumanInputForm] = {}
        self._form_ids_by_node: dict[str, str] = {}
        self._sequence = 0

    def clone(self) -> AcceptanceHumanInputFormRepository:
        cloned = AcceptanceHumanInputFormRepository()
        cloned._forms_by_id = deepcopy(self._forms_by_id)
        cloned._form_ids_by_node = dict(self._form_ids_by_node)
        cloned._sequence = self._sequence
        return cloned

    def get_form(self, node_id: str, *, form_id: str | None = None) -> AcceptanceHumanInputForm | None:
        resolved_id = form_id or self._form_ids_by_node.get(node_id)
        return self._forms_by_id.get(resolved_id) if resolved_id is not None else None

    def create_form(self, params: FormCreateParams) -> AcceptanceHumanInputForm:
        self._sequence += 1
        form_id = params.form_id or f"assist-form-{params.node_id}-{self._sequence}"
        created_at = naive_utc_now()
        form = AcceptanceHumanInputForm(
            id=form_id,
            rendered_content=params.rendered_content,
            created_at=created_at,
            expiration_time=params.form_config.expiration_time(created_at),
            form_config=params.form_config,
            resolved_default_values=dict(params.resolved_default_values),
        )
        self._forms_by_id[form_id] = form
        self._form_ids_by_node[params.node_id] = form_id
        return form

    def submit(self, *, form_id: str, action_id: str) -> dict[str, Any]:
        form = self._forms_by_id[form_id]
        form_data = _fixture_form_data(form)
        form.selected_action_id = action_id
        form.submitted_data = form_data
        form.status = HumanInputFormStatus.SUBMITTED
        return form_data


def _fixture_form_data(form: AcceptanceHumanInputForm) -> dict[str, Any]:
    config = form.form_config
    inputs = getattr(config, "inputs", [])
    values: dict[str, Any] = {}
    for item in inputs:
        name = item.output_variable_name
        if name in form.resolved_default_values:
            values[name] = deepcopy(form.resolved_default_values[name])
            continue
        if isinstance(item, ParagraphInputConfig):
            default = item.default
            values[name] = (
                default.value
                if default is not None and default.type == ValueSourceType.CONSTANT
                else "acceptance"
            )
            continue
        if isinstance(item, SelectInputConfig):
            source = item.option_source
            if source.type == ValueSourceType.CONSTANT and source.value:
                values[name] = source.value[0]
            else:
                values[name] = "acceptance"
            continue
        if isinstance(item, FileInputConfig | FileListInputConfig):
            raise UnsupportedHumanInputFixtureError(f"Human Input field {name!r} requires a real file")
        raise UnsupportedHumanInputFixtureError(f"Human Input field {name!r} has an unsupported type")
    return values

