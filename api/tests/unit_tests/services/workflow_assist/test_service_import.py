import importlib


def test_workflow_assist_service_imports_with_the_current_chat_facade() -> None:
    module = importlib.import_module("services.workflow_assist.service")

    assert module.WorkflowAssistService is not None
