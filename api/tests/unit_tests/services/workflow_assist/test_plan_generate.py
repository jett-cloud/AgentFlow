import importlib

import pytest

from services.workflow_assist.service import WorkflowAssistService

_ASSIST_PLAN_GENERATE_ENTRYPOINTS = [
    "propose_plan",
    "iter_propose_plan_events",
    "generate",
    "iter_generate_events",
    "record_conversation_request",
    "commit_planning_checkpoint",
    "record_conversation_events",
    "record_conversation_message",
    "resolve_clarification_response",
    "assert_conversation_plan_is_current",
]


@pytest.mark.parametrize(
    "module_name",
    ["services.workflow_assist.plan", "services.workflow_assist.generate"],
)
def test_assist_plan_and_generate_adapter_modules_are_gone(module_name: str) -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


@pytest.mark.parametrize("name", _ASSIST_PLAN_GENERATE_ENTRYPOINTS)
def test_assist_service_has_no_plan_or_generate_entrypoints(name: str) -> None:
    assert not hasattr(WorkflowAssistService, name)
