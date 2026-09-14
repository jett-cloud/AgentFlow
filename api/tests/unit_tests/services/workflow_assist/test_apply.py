from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from core.workflow.generator.acceptance.evidence import canonical_graph_hash
from core.workflow.generator.contracts.workflow_contract import canonical_workflow_contract_hash
from core.workflow.generator.contracts.workflow_reconciliation import WORKFLOW_RECONCILIATION_VERSION
from core.workflow.generator.graph.graph_postprocessor import postprocess_graph
from models.agent_config_entities import AgentSoulConfig
from models.workflow import Workflow, WorkflowType
from models.workflow_assist import (
    WorkflowAssistCompletionAssertion,
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistMode,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    WorkflowAssistRunEventType,
    WorkflowAssistRunStatus,
)
from services.agent.errors import InvalidComposerConfigError
from services.errors.app import WorkflowHashNotEqualError
from services.workflow_assist import apply as apply_module
from services.workflow_assist import chat as chat_module
from services.workflow_assist import service as service_module
from services.workflow_assist.apply import WorkflowAssistInvalidGraphError
from services.workflow_assist.conversations import WorkflowAssistConversationNotFound, WorkflowAssistConversationService
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import CandidateMutation, CommitStepOutcome, RunOwner
from services.workflow_assist.service import WorkflowAssistService
from services.workflow_service import WorkflowService
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config

TABLES = (
    WorkflowAssistConversation,
    WorkflowAssistMessage,
    WorkflowAssistRun,
    WorkflowAssistRunEvent,
    Workflow,
)
BASE_HASH = "a" * 64
NEXT_HASH = "b" * 64
SERVER_GRAPH = {
    "nodes": [
        {"id": "server-node", "data": node_config("start", {"type": "start"})},
        {"id": "server-end", "data": node_config("end", {"type": "end"})},
    ],
    "edges": [{"source": "server-node", "target": "server-end"}],
}


def _tool_candidate_graph() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "start", "data": node_config("start", {"type": "start", "variables": []})},
            {
                "id": "tool_1",
                "data": {
                    "type": "tool",
                    "provider_id": "image/provider",
                    "provider_name": "image/provider",
                    "provider_type": "builtin",
                    "tool_name": "generate",
                    "tool_label": "Generate",
                    "tool_node_version": "2",
                    "tool_parameters": {"prompt": {"type": "constant", "value": "draw"}},
                    "tool_configurations": {},
                },
            },
            {"id": "end", "data": node_config("end", {"type": "end"})},
        ],
        "edges": [{"source": "start", "target": "tool_1"}, {"source": "tool_1", "target": "end"}],
    }


def _tool_entry() -> dict[str, object]:
    return {
        "provider_name": "image/provider",
        "provider_type": "builtin",
        "plugin_id": "image/provider",
        "tool_name": "generate",
        "tool_label": "Generate",
        "description": "Generate an image",
        "parameters": (
            {"name": "prompt", "type": "string", "form": "llm", "required": True},
            {"name": "size", "type": "select", "form": "form", "required": False, "default": "2K"},
        ),
        "parameter_names": ("prompt", "size"),
        "output_names": ("files",),
    }


def _app(mode: str = "workflow") -> SimpleNamespace:
    return SimpleNamespace(id="app-1", tenant_id="tenant-1", mode=mode)


def _account() -> SimpleNamespace:
    return SimpleNamespace(id="account-1")


def _seed_completed_candidate(session: Session) -> tuple[WorkflowAssistConversation, WorkflowAssistRun]:
    conversation = WorkflowAssistConversation(
        id="conversation-1",
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        draft_hash=BASE_HASH,
        state={},
        candidate_graph=SERVER_GRAPH,
        candidate_revision=3,
        candidate_base_hash=BASE_HASH,
        run_epoch=1,
        completion_run_id="run-1",
        completion_epoch=1,
        completion_candidate_revision=3,
        completion_candidate_base_hash=BASE_HASH,
        completion_app_mode=WorkflowAssistMode.WORKFLOW,
        completion_assertion=WorkflowAssistCompletionAssertion.WORKFLOW_STRUCTURE_REACHES_TERMINAL,
        contract_protocol_version=None,
    )
    run = WorkflowAssistRun(
        id="run-1",
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        epoch=1,
        status=WorkflowAssistRunStatus.DONE,
        input="Build it",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
        candidate_revision=3,
    )
    conversation.latest_run_id = run.id
    session.add_all([conversation, run])
    session.flush()
    # This helper models a pre-contract conversation; SQLAlchemy's insert
    # default otherwise upgrades an explicit None to protocol 1.
    conversation.contract_protocol_version = None
    session.commit()
    return conversation, run


def _enable_contract_completion(conversation: WorkflowAssistConversation) -> dict[str, object]:
    graph: dict[str, object] = {
        "nodes": [
            {
                "id": "start",
                "data": {
                    "type": "start",
                    "variables": [
                        {
                            "variable": "query",
                            "label": "Query",
                            "type": "paragraph",
                            "required": True,
                            "max_length": 4096,
                            "options": [],
                        }
                    ],
                },
            },
            {
                "id": "terminal",
                "data": node_config(
                    "end",
                    {
                        "type": "end",
                        "outputs": [
                            {
                                "variable": "result",
                                "value_selector": ["start", "query"],
                                "value_type": "string",
                            }
                        ],
                    },
                ),
            },
        ],
        "edges": [{"source": "start", "target": "terminal"}],
    }
    contract_body = {
        "schema_version": 1,
        "status": "complete",
        "operation": "rebuild",
        "requirements": [
            {
                "id": "req.result",
                "source_turn_id": "turn:1",
                "evidence": "Build it",
                "text": "Build it",
                "provenance": "explicit_user",
                "supersedes": [],
            }
        ],
        "assumptions": [],
        "edit_scope": None,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "objective": "Collect query",
                "requirement_ids": ["req.result"],
                "inputs": [],
                "outputs": [{"name": "query", "type": "string"}],
                "structure_kind": "start",
                "unresolved": [],
            },
            {
                "id": "terminal",
                "type": "end",
                "objective": "Return result",
                "requirement_ids": ["req.result"],
                "inputs": [{"source": ["start", "query"], "role": "result"}],
                "outputs": [{"name": "result", "type": "string"}],
                "structure_kind": "end",
                "unresolved": [],
            },
        ],
        "edges": [{"source": "start", "target": "terminal", "source_handle": None}],
        "final_outputs": [{"name": "result", "source": ["terminal", "result"], "type": "string"}],
        "resources": [],
        "checks": [
            {
                "id": "check.result",
                "description": "Terminal returns result",
                "level": "static",
                "requirement_ids": ["req.result"],
            }
        ],
        "unresolved": [],
    }
    graph = postprocess_graph(graph=graph, mode="workflow")
    contract_hash = canonical_workflow_contract_hash(contract_body, revision=1)
    conversation.candidate_graph = graph
    conversation.contract_protocol_version = 1
    conversation.contract_revision = 1
    conversation.contract_hash = contract_hash
    conversation.workflow_contract = {
        **contract_body,
        "protocol_version": 1,
        "revision": 1,
        "contract_hash": contract_hash,
    }
    conversation.completion_contract_protocol_version = 1
    conversation.completion_contract_revision = 1
    conversation.completion_contract_hash = contract_hash
    conversation.completion_graph_hash = canonical_graph_hash(graph)
    conversation.completion_validation_version = WORKFLOW_RECONCILIATION_VERSION
    return graph


def _enable_tool_contract_completion(conversation: WorkflowAssistConversation) -> None:
    graph = deepcopy(_enable_contract_completion(conversation))
    tool_node = deepcopy(_tool_candidate_graph()["nodes"][1])  # type: ignore[index]
    graph["nodes"].insert(1, tool_node)  # type: ignore[union-attr]
    graph["edges"] = [
        {"source": "start", "target": "tool_1"},
        {"source": "tool_1", "target": "terminal"},
    ]
    graph = postprocess_graph(graph=graph, mode="workflow", tool_entries=[_tool_entry()])
    contract = deepcopy(conversation.workflow_contract)
    assert isinstance(contract, dict)
    contract["nodes"].insert(  # type: ignore[union-attr]
        1,
        {
            "id": "tool_1",
            "type": "tool",
            "objective": "Generate an image",
            "requirement_ids": ["req.result"],
            "inputs": [],
            "outputs": [],
            "structure_kind": None,
            "unresolved": [],
        },
    )
    contract["edges"] = [
        {"source": "start", "target": "tool_1", "source_handle": None},
        {"source": "tool_1", "target": "terminal", "source_handle": None},
    ]
    contract["resources"] = [
        {
            "kind": "tool",
            "provider_name": "image/provider",
            "tool_name": "generate",
            "consumer_id": "tool_1",
            "verified": True,
            "unresolved_reason": None,
        }
    ]
    for field in ("protocol_version", "revision", "contract_hash"):
        contract.pop(field, None)
    contract_hash = canonical_workflow_contract_hash(contract, revision=1)
    conversation.workflow_contract = {
        **contract,
        "protocol_version": 1,
        "revision": 1,
        "contract_hash": contract_hash,
    }
    conversation.contract_hash = contract_hash
    conversation.completion_contract_hash = contract_hash
    conversation.candidate_graph = graph
    conversation.completion_graph_hash = canonical_graph_hash(graph)


def _workflow_service(draft_hash: str = BASE_HASH) -> MagicMock:
    service = MagicMock()
    service.get_draft_workflow.return_value = SimpleNamespace(
        id="workflow-1",
        unique_hash=draft_hash,
        features_dict={"opening_statement": "Welcome"},
        environment_variables=["environment-variable"],
        conversation_variables=["conversation-variable"],
        _environment_variables="{}",
        _conversation_variables="{}",
    )
    service.sync_draft_workflow.return_value = SimpleNamespace(unique_hash=NEXT_HASH)
    return service


def _apply(session: Session) -> dict[str, str]:
    return apply_module.apply_draft(
        session=session,
        app_model=_app(),
        account=_account(),
        conversation_id="conversation-1",
        unique_hash=BASE_HASH,
    )


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_uses_only_server_candidate_and_atomically_clears_evidence(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    result = _apply(sqlite_session)

    assert result == {"hash": NEXT_HASH}
    applied = workflow_service.sync_draft_workflow.call_args.kwargs
    assert applied["features"] == {"opening_statement": "Welcome"}
    assert applied["unique_hash"] == BASE_HASH
    assert applied["environment_variables"] == ["environment-variable"]
    assert applied["conversation_variables"] == ["conversation-variable"]
    assert applied["session"] is sqlite_session
    assert applied["commit"] is False
    assert applied["graph"]["nodes"][0]["id"] == "servernode"
    assert applied["graph"]["nodes"][0]["position"]["x"] == 80.0
    sqlite_session.refresh(conversation)
    assert conversation.draft_hash == NEXT_HASH
    assert conversation.candidate_graph is None
    assert conversation.candidate_base_hash is None
    assert conversation.candidate_revision == 3
    assert conversation.completion_run_id is None
    assert conversation.completion_epoch is None
    assert conversation.completion_candidate_revision is None
    assert conversation.completion_candidate_base_hash is None
    assert conversation.completion_app_mode is None
    assert conversation.completion_assertion is None
    assert conversation.completion_contract_protocol_version is None
    assert conversation.completion_contract_revision is None
    assert conversation.completion_contract_hash is None
    assert conversation.completion_graph_hash is None
    assert conversation.completion_validation_version is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_reconciles_current_contract_and_graph_before_sync(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    _enable_contract_completion(conversation)
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    result = _apply(sqlite_session)

    assert result == {"hash": NEXT_HASH}
    workflow_service.sync_draft_workflow.assert_called_once()


@pytest.mark.parametrize("stale_fact", ["contract", "graph"])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_contract_or_graph_changed_after_completion(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    stale_fact: str,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    graph = _enable_contract_completion(conversation)
    if stale_fact == "contract":
        conversation.contract_revision = 2
    else:
        changed = deepcopy(graph)
        changed["nodes"][0]["data"]["title"] = "Changed after finish"  # type: ignore[index]
        conversation.candidate_graph = changed
    sqlite_session.commit()
    workflow_service_type.return_value = _workflow_service()

    with pytest.raises(apply_module.WorkflowAssistApplyConflictError):
        _apply(sqlite_session)

    workflow_service_type.return_value.sync_draft_workflow.assert_not_called()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_resource_removed_since_finish(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    _enable_tool_contract_completion(conversation)
    sqlite_session.commit()
    monkeypatch.setattr("services.workflow_assist.validation_context.build_tool_catalogue", MagicMock(return_value=[]))
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert any(error["code"] == "WORKFLOW_CONTRACT_MISMATCH" for error in raised.value.errors)
    assert any("image/provider" in error["detail"] for error in raised.value.errors)
    workflow_service.sync_draft_workflow.assert_not_called()
    sqlite_session.refresh(conversation)
    assert conversation.candidate_graph is not None
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_model_removed_since_finish(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    graph = deepcopy(_enable_contract_completion(conversation))
    graph["nodes"][1]["data"]["model"] = {  # type: ignore[index]
        "provider": "openai",
        "name": "gpt-4o",
        "mode": "chat",
    }
    contract = deepcopy(conversation.workflow_contract)
    assert isinstance(contract, dict)
    contract["resources"] = [
        {
            "kind": "model",
            "provider": "openai",
            "name": "gpt-4o",
            "mode": "chat",
            "consumer_id": "terminal",
            "verified": True,
            "unresolved_reason": None,
        }
    ]
    for field in ("protocol_version", "revision", "contract_hash"):
        contract.pop(field, None)
    contract_hash = canonical_workflow_contract_hash(contract, revision=1)
    conversation.workflow_contract = {
        **contract,
        "protocol_version": 1,
        "revision": 1,
        "contract_hash": contract_hash,
    }
    conversation.contract_hash = contract_hash
    conversation.completion_contract_hash = contract_hash
    conversation.candidate_graph = graph
    conversation.completion_graph_hash = canonical_graph_hash(graph)
    sqlite_session.commit()
    monkeypatch.setattr(
        "services.workflow_assist.validation_context.build_agent_model_catalogue",
        MagicMock(return_value=()),
    )
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert any(error["code"] == "WORKFLOW_CONTRACT_MISMATCH" for error in raised.value.errors)
    assert any("gpt-4o" in error["detail"] for error in raised.value.errors)
    workflow_service.sync_draft_workflow.assert_not_called()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_normalizes_and_validates_with_one_tool_catalogue_snapshot(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = _tool_candidate_graph()
    sqlite_session.commit()
    catalogue = MagicMock(return_value=[_tool_entry()])
    monkeypatch.setattr("services.workflow_assist.validation_context.build_tool_catalogue", catalogue)
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    _apply(sqlite_session)

    applied = workflow_service.sync_draft_workflow.call_args.kwargs["graph"]
    tool = next(node for node in applied["nodes"] if node["id"] == "tool_1")
    assert tool["data"]["tool_parameters"]["size"] == {"type": "constant", "value": "2K"}
    assert tool["data"]["tool_configurations"]["size"] == "2K"
    catalogue.assert_called_once_with("tenant-1", limit=None, raise_on_error=True)


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_tool_catalogue_failure_is_capability_unavailable_without_write(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = _tool_candidate_graph()
    sqlite_session.commit()
    monkeypatch.setattr(
        "services.workflow_assist.validation_context.build_tool_catalogue",
        MagicMock(side_effect=RuntimeError("catalogue unavailable")),
    )
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert raised.value.errors == [
        {"code": "CAPABILITY_UNAVAILABLE", "detail": "Unable to load tenant validation resources"}
    ]
    workflow_service.sync_draft_workflow.assert_not_called()
    sqlite_session.refresh(conversation)
    assert conversation.candidate_graph == _tool_candidate_graph()
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_bare_array_code_output_without_writing_draft(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {
                "id": "node_parse",
                "data": {"type": "code", "outputs": {"questions": {"type": "array"}}},
            },
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [
            {"source": "start", "target": "node_parse"},
            {"source": "node_parse", "target": "end"},
        ],
    }
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service
    before = dict(conversation.candidate_graph)

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert any(error["code"] == "INVALID_CODE_OUTPUT" for error in raised.value.errors)
    workflow_service.sync_draft_workflow.assert_not_called()
    sqlite_session.refresh(conversation)
    assert conversation.candidate_graph == before
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_runtime_valid_http_with_empty_url_without_writing_draft(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start", "variables": []}},
            {
                "id": "request",
                "data": {
                    "type": "http-request",
                    "method": "get",
                    "url": "  ",
                    "authorization": {"type": "no-auth", "config": None},
                    "headers": "",
                    "params": "",
                    "body": {"type": "none", "data": []},
                },
            },
            {"id": "end", "data": {"type": "end", "outputs": []}},
        ],
        "edges": [{"source": "start", "target": "request"}, {"source": "request", "target": "end"}],
    }
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service
    before = deepcopy(conversation.candidate_graph)

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert any(error["code"] == "INVALID_NODE_CONFIG" and "url" in error["detail"] for error in raised.value.errors)
    workflow_service.sync_draft_workflow.assert_not_called()
    sqlite_session.refresh(conversation)
    assert conversation.candidate_graph == before
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_unhydrated_agent_binding_without_writing_draft(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {
                "id": "agent_1",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_node_kind": "dify_agent",
                    "agent_task": "调查问题",
                    "agent_binding": {"binding_type": "inline_agent"},
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
                },
            },
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [
            {"source": "start", "target": "agent_1"},
            {"source": "agent_1", "target": "end"},
        ],
    }
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert any(error["code"] == "AGENT_BINDING_MISSING" for error in raised.value.errors)
    workflow_service.sync_draft_workflow.assert_not_called()
    sqlite_session.refresh(conversation)
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=None)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_untrusted_agent_binding_ids_without_writing_draft(
    workflow_service_type: MagicMock,
    load_trusted: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start"}},
            {
                "id": "agent_1",
                "data": {
                    "type": "agent",
                    "version": "2",
                    "agent_node_kind": "dify_agent",
                    "agent_task": "调查问题",
                    "agent_binding": {
                        "binding_type": "inline_agent",
                        "agent_id": "forged-agent",
                        "current_snapshot_id": "forged-snap",
                    },
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat"},
                },
            },
            {"id": "end", "data": {"type": "end"}},
        ],
        "edges": [
            {"source": "start", "target": "agent_1"},
            {"source": "agent_1", "target": "end"},
        ],
    }
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
        _apply(sqlite_session)

    assert any(error["code"] == "INVALID_AGENT_NODE" for error in raised.value.errors)
    workflow_service.sync_draft_workflow.assert_not_called()
    sqlite_session.refresh(conversation)
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_translates_snapshot_knowledge_validation_to_unknown_dataset(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": node_config("start", {"type": "start", "variables": []})},
            {
                "id": "agent_1",
                "data": node_config(
                    "agent",
                    {
                        "type": "agent",
                        "version": "2",
                        "agent_node_kind": "dify_agent",
                        "agent_task": "Answer",
                        "agent_binding": {
                            "binding_type": "inline_agent",
                            "agent_id": "aid",
                            "current_snapshot_id": "sid",
                        },
                        "model": {
                            "provider": "langgenius/openai/openai",
                            "name": "gpt-4o",
                            "mode": "chat",
                        },
                    },
                ),
            },
            {"id": "end", "data": node_config("end", {"type": "end", "outputs": []})},
        ],
        "edges": [{"source": "start", "target": "agent_1"}, {"source": "agent_1", "target": "end"}],
    }
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service
    soul = AgentSoulConfig.model_validate(
        {
            "model": {
                "plugin_id": "langgenius/openai",
                "model_provider": "langgenius/openai/openai",
                "model": "gpt-4o",
            },
            "knowledge": {
                "sets": [
                    {
                        "id": "ks-1",
                        "name": "Docs",
                        "datasets": [{"id": "missing-dataset"}],
                        "query": {"mode": "generated_query"},
                        "retrieval": {"mode": "multiple", "top_k": 4, "reranking_enable": False},
                    }
                ]
            },
        }
    )
    trusted = SimpleNamespace(
        agent=SimpleNamespace(id="aid"),
        snapshot=SimpleNamespace(id="sid", config_snapshot=soul),
    )

    with (
        patch("services.workflow_assist.hydrate._load_trusted_inline_binding", return_value=trusted),
        patch(
            "services.workflow_assist.hydrate.AgentComposerService.validate_knowledge_datasets",
            side_effect=InvalidComposerConfigError("knowledge_dataset_not_found"),
        ),
        patch("services.workflow_assist.apply.activate_candidate_bindings") as activate,
    ):
        with pytest.raises(WorkflowAssistInvalidGraphError) as raised:
            _apply(sqlite_session)

    assert any(error["code"] == "UNKNOWN_DATASET" for error in raised.value.errors)
    activate.assert_not_called()
    workflow_service.sync_draft_workflow.assert_not_called()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_lays_out_linear_nodes_and_container_children(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "services.workflow_assist.validation_context.build_knowledge_catalogue",
        lambda *args, **kwargs: [{"id": "ds-1"}],
    )
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start", "title": "开始", "variables": []}},
            {
                "id": "kb_retrieval",
                "data": {
                    "type": "knowledge-retrieval",
                    "title": "检索",
                    "dataset_ids": ["ds-1"],
                    "query_variable_selector": ["start", "query"],
                    "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
                },
            },
            {"id": "llm", "data": {"type": "llm", "title": "生成答案"}},
            {
                "id": "end",
                "data": {
                    "type": "end",
                    "title": "结束",
                    "outputs": [{"variable": "answer", "value_selector": ["llm", "text"], "value_type": "string"}],
                },
            },
            {"id": "loop1", "data": {"type": "loop", "title": "循环", "start_node_id": "loop1start"}},
            {
                "id": "loop1start",
                "type": "custom-loop-start",
                "parentId": "loop1",
                "data": {"type": "loop-start"},
            },
            {
                "id": "loop_body",
                "parentId": "loop1",
                "data": {"type": "code", "outputs": {"result": {"type": "string"}}},
            },
        ],
        "edges": [
            {"source": "start", "target": "kb_retrieval"},
            {"source": "kb_retrieval", "target": "llm"},
            {"source": "llm", "target": "end"},
            {"source": "start", "target": "loop1"},
            {"source": "loop1start", "target": "loop_body"},
        ],
    }
    for node in conversation.candidate_graph["nodes"]:
        node["data"] = node_config(node["data"]["type"], node["data"])
    sqlite_session.commit()
    workflow_service = _workflow_service()
    workflow_service_type.return_value = workflow_service

    _apply(sqlite_session)

    nodes = {node["id"]: node for node in workflow_service.sync_draft_workflow.call_args.kwargs["graph"]["nodes"]}
    assert nodes["start"]["position"]["x"] < nodes["kb_retrieval"]["position"]["x"]
    assert nodes["kb_retrieval"]["position"]["x"] < nodes["llm"]["position"]["x"]
    assert nodes["llm"]["position"]["x"] < nodes["end"]["position"]["x"]
    assert nodes["loop1start"]["position"]["x"] < nodes["loop_body"]["position"]["x"]
    assert nodes["loop1"]["width"] > nodes["loop_body"]["position"]["x"]


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_any_owner_scoped_active_run(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    active = WorkflowAssistRun(
        id="run-2",
        tenant_id="tenant-1",
        app_id="app-1",
        created_by="account-1",
        conversation_id="conversation-1",
        epoch=2,
        status=WorkflowAssistRunStatus.RUNNING,
        input="Change it",
        mode=WorkflowAssistMode.WORKFLOW,
        model_config={},
        candidate_revision=3,
    )
    conversation.active_run_id = active.id
    conversation.latest_run_id = active.id
    conversation.run_epoch = 2
    sqlite_session.add(active)
    sqlite_session.commit()
    workflow_service_type.return_value = _workflow_service()

    with pytest.raises(apply_module.WorkflowAssistApplyConflictError) as raised:
        _apply(sqlite_session)

    assert raised.value.active_run is not None
    assert raised.value.active_run.run_id == "run-2"
    workflow_service_type.return_value.sync_draft_workflow.assert_not_called()


@pytest.mark.parametrize(
    ("mutation", "draft_hash"),
    [
        (lambda conversation, _run: setattr(conversation, "candidate_graph", None), BASE_HASH),
        (lambda conversation, _run: setattr(conversation, "candidate_base_hash", "c" * 64), BASE_HASH),
        (lambda _conversation, _run: None, "c" * 64),
        (lambda conversation, _run: setattr(conversation, "completion_run_id", None), BASE_HASH),
        (lambda conversation, _run: setattr(conversation, "completion_run_id", "run-other"), BASE_HASH),
        (lambda conversation, _run: setattr(conversation, "completion_epoch", 2), BASE_HASH),
        (lambda conversation, _run: setattr(conversation, "completion_candidate_revision", 4), BASE_HASH),
        (lambda conversation, _run: setattr(conversation, "completion_candidate_base_hash", "c" * 64), BASE_HASH),
        (
            lambda conversation, _run: setattr(conversation, "completion_app_mode", WorkflowAssistMode.ADVANCED_CHAT),
            BASE_HASH,
        ),
        (lambda conversation, _run: setattr(conversation, "completion_assertion", None), BASE_HASH),
        (lambda _conversation, run: setattr(run, "status", WorkflowAssistRunStatus.ABORTED), BASE_HASH),
    ],
    ids=[
        "missing-candidate",
        "candidate-base",
        "draft-hash",
        "missing-evidence",
        "run-id",
        "epoch",
        "revision",
        "evidence-base",
        "app-mode",
        "assertion",
        "run-status",
    ],
)
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rejects_every_stale_candidate_or_completion_fact(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    mutation,
    draft_hash: str,
) -> None:
    conversation, run = _seed_completed_candidate(sqlite_session)
    mutation(conversation, run)
    sqlite_session.commit()
    workflow_service_type.return_value = _workflow_service(draft_hash)

    with pytest.raises(apply_module.WorkflowAssistApplyConflictError):
        _apply(sqlite_session)

    workflow_service_type.return_value.sync_draft_workflow.assert_not_called()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_validates_complete_conversation_ownership(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    _seed_completed_candidate(sqlite_session)
    workflow_service_type.return_value = _workflow_service()

    with pytest.raises(WorkflowAssistConversationNotFound):
        apply_module.apply_draft(
            session=sqlite_session,
            app_model=SimpleNamespace(id="app-1", tenant_id="other-tenant", mode="workflow"),
            account=_account(),
            conversation_id="conversation-1",
            unique_hash=BASE_HASH,
        )

    workflow_service_type.return_value.sync_draft_workflow.assert_not_called()


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_rolls_back_candidate_cleanup_when_draft_sync_fails(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    workflow_service = _workflow_service()
    workflow_service.sync_draft_workflow.side_effect = RuntimeError("sync failed")
    workflow_service_type.return_value = workflow_service

    with pytest.raises(RuntimeError, match="sync failed"):
        _apply(sqlite_session)

    sqlite_session.refresh(conversation)
    assert conversation.candidate_graph == SERVER_GRAPH
    assert conversation.candidate_base_hash == BASE_HASH
    assert conversation.completion_run_id == "run-1"


@pytest.mark.parametrize("legacy_draft_hash", [None, "a" * 32], ids=["empty", "legacy-32"])
@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_real_turn_worker_candidate_done_apply_flow_freezes_server_draft_hash(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    legacy_draft_hash: str | None,
) -> None:
    base_graph = {
        "nodes": [
            {"id": "start", "data": node_config("start", {"type": "start"})},
            {"id": "terminal", "data": node_config("end", {"type": "end"})},
        ],
        "edges": [{"source": "start", "target": "terminal"}],
    }
    draft = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type=WorkflowType.WORKFLOW,
        version=Workflow.VERSION_DRAFT,
        graph=json.dumps(base_graph),
        _features="{}",
        created_by="account-1",
        environment_variables=[],
        conversation_variables=[],
    )
    sqlite_session.add(draft)
    conversation = WorkflowAssistConversationService(sqlite_session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        draft_hash=legacy_draft_hash,
    )
    conversation.id = "conversation-1"
    sqlite_session.commit()
    conversation.contract_protocol_version = None
    sqlite_session.commit()
    canonical_base = draft.unique_hash
    app_model = _app()
    account = _account()
    monkeypatch.setattr(WorkflowAssistService, "dispatch_run", MagicMock())

    run = WorkflowAssistService.start_turn(
        session=sqlite_session,
        app_model=app_model,
        account=account,
        conversation_id=conversation.id,
        message="Build it",
        mode="workflow",
        model_config={},
    )
    owner = RunOwner("tenant-1", "app-1", "account-1", conversation.id)
    coordinator = RunCoordinator(sqlite_session)
    lease = coordinator.claim(owner=owner, run_id=run.id, epoch=run.epoch, worker_id="delivery-1")
    assert lease is not None
    sqlite_session.commit()
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(chat_module.session_factory, "create_session", maker)

    worker_base = chat_module._load_candidate_base_hash(lease)
    assert worker_base == canonical_base
    candidate_graph = {
        "nodes": [
            {"id": "start", "data": node_config("start", {"type": "start"})},
            {"id": "answer", "data": node_config("end", {"type": "end"})},
        ],
        "edges": [{"source": "start", "target": "answer"}],
    }
    committed = coordinator.commit_step(
        lease=lease,
        step_id="candidate-1",
        event="candidate.updated",
        payload={"diff": {"added": ["answer"], "removed": [], "changed": []}},
        candidate=CandidateMutation(graph=candidate_graph, base_hash=worker_base),
    )
    assert committed.outcome is CommitStepOutcome.COMMITTED
    assert coordinator.terminate(
        lease=lease,
        status="done",
        step_id="terminal-done",
        payload={},
        reason="completed",
    )
    sqlite_session.commit()
    monkeypatch.setattr(
        "services.agent.workflow_publish_service.WorkflowAgentPublishService.sync_agent_bindings_for_draft",
        MagicMock(),
    )
    monkeypatch.setattr(
        "services.agent.workflow_publish_service.WorkflowAgentPublishService.validate_agent_nodes_for_draft_sync",
        MagicMock(),
    )
    monkeypatch.setattr(apply_module.app_draft_workflow_was_synced, "send", MagicMock())

    result = apply_module.apply_draft(
        session=sqlite_session,
        app_model=app_model,
        account=account,
        conversation_id=conversation.id,
        unique_hash=canonical_base,
    )

    assert len(canonical_base) == 64
    assert result["hash"] == sqlite_session.get(Workflow, draft.id).unique_hash
    sqlite_session.refresh(conversation)
    assert conversation.draft_hash == result["hash"]
    assert conversation.candidate_graph is None
    assert conversation.completion_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_turn_freeze_preserves_an_existing_candidate_base(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type=WorkflowType.WORKFLOW,
        version=Workflow.VERSION_DRAFT,
        graph=json.dumps({"nodes": [], "edges": []}),
        _features="{}",
        created_by="account-1",
        environment_variables=[],
        conversation_variables=[],
    )
    sqlite_session.add(draft)
    conversation = WorkflowAssistConversationService(sqlite_session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        draft_hash="a" * 32,
    )
    conversation.id = "conversation-1"
    conversation.candidate_graph = {"nodes": [], "edges": []}
    conversation.candidate_base_hash = "c" * 64
    sqlite_session.commit()
    monkeypatch.setattr(WorkflowAssistService, "dispatch_run", MagicMock())

    WorkflowAssistService.start_turn(
        session=sqlite_session,
        app_model=_app(),
        account=_account(),
        conversation_id=conversation.id,
        message="Continue",
        mode="workflow",
        model_config={},
    )

    sqlite_session.refresh(conversation)
    assert conversation.draft_hash == draft.unique_hash
    assert conversation.candidate_base_hash == "c" * 64
    assert conversation.candidate_graph == {"nodes": [], "edges": []}


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_new_conversation_turn_seeds_candidate_from_current_draft(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applied_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start", "title": "Start"}},
            {"id": "llm", "data": {"type": "llm", "title": "Summarize"}},
            {"id": "end", "data": {"type": "end", "title": "End"}},
        ],
        "edges": [{"source": "start", "target": "llm"}, {"source": "llm", "target": "end"}],
    }
    draft = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type=WorkflowType.WORKFLOW,
        version=Workflow.VERSION_DRAFT,
        graph=json.dumps(applied_graph),
        _features="{}",
        created_by="account-1",
        environment_variables=[],
        conversation_variables=[],
    )
    sqlite_session.add(draft)
    first = WorkflowAssistConversationService(sqlite_session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
    )
    first.id = "conversation-1"
    sqlite_session.commit()
    monkeypatch.setattr(WorkflowAssistService, "dispatch_run", MagicMock())

    WorkflowAssistService.start_turn(
        session=sqlite_session,
        app_model=_app(),
        account=_account(),
        conversation_id=first.id,
        message="Build a summarizer",
        mode="workflow",
        model_config={},
    )
    sqlite_session.refresh(first)
    first.candidate_graph = None
    first.candidate_base_hash = None
    sqlite_session.commit()

    second = WorkflowAssistConversationService(sqlite_session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
        title="Follow-up edit",
    )
    second.id = "conversation-2"
    sqlite_session.commit()
    assert second.candidate_graph is None

    WorkflowAssistService.start_turn(
        session=sqlite_session,
        app_model=_app(),
        account=_account(),
        conversation_id=second.id,
        message="Read the current workflow and add a knowledge node",
        mode="workflow",
        model_config={},
    )

    sqlite_session.refresh(second)
    assert second.candidate_graph is not None
    node_ids = {node["id"] for node in second.candidate_graph["nodes"]}
    assert node_ids == {"start", "llm", "end"}
    assert second.candidate_base_hash == draft.unique_hash
    assert second.draft_hash == draft.unique_hash


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
def test_broker_failure_is_compensated_to_a_terminal_owned_run(
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = Workflow(
        id="workflow-1",
        tenant_id="tenant-1",
        app_id="app-1",
        type=WorkflowType.WORKFLOW,
        version=Workflow.VERSION_DRAFT,
        graph=json.dumps({"nodes": [], "edges": []}),
        _features="{}",
        created_by="account-1",
        environment_variables=[],
        conversation_variables=[],
    )
    sqlite_session.add(draft)
    conversation = WorkflowAssistConversationService(sqlite_session).create(
        tenant_id="tenant-1",
        app_id="app-1",
        account_id="account-1",
    )
    conversation.id = "conversation-1"
    sqlite_session.commit()
    maker = sessionmaker(bind=sqlite_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(service_module.session_factory, "create_session", maker)
    monkeypatch.setattr(
        WorkflowAssistService,
        "dispatch_run",
        MagicMock(side_effect=RuntimeError("broker unavailable")),
    )

    run = WorkflowAssistService.start_turn(
        session=sqlite_session,
        app_model=_app(),
        account=_account(),
        conversation_id=conversation.id,
        message="Build it",
        mode="workflow",
        model_config={},
    )

    sqlite_session.expire_all()
    persisted_run = sqlite_session.get(WorkflowAssistRun, run.id)
    assert persisted_run is not None
    assert persisted_run.status is WorkflowAssistRunStatus.ERROR
    assert persisted_run.termination_reason == "dispatch_failed"
    persisted_conversation = sqlite_session.get(WorkflowAssistConversation, conversation.id)
    assert persisted_conversation is not None
    assert persisted_conversation.active_run_id is None
    assert persisted_conversation.latest_run_id == run.id
    event = (
        sqlite_session.query(WorkflowAssistRunEvent)
        .filter_by(run_id=run.id)
        .order_by(WorkflowAssistRunEvent.sequence.desc())
        .first()
    )
    assert event is not None
    assert event.event is WorkflowAssistRunEventType.ERROR
    assert event.payload == {"status": "error", "reason": "dispatch_failed"}


def test_ordinary_draft_sync_locks_and_refreshes_before_stale_hash_check() -> None:
    session = MagicMock()
    session.scalar.return_value = SimpleNamespace(unique_hash=NEXT_HASH)
    workflow_service = object.__new__(WorkflowService)

    with pytest.raises(WorkflowHashNotEqualError):
        workflow_service.sync_draft_workflow(
            app_model=_app(),
            graph=SERVER_GRAPH,
            features={},
            unique_hash=BASE_HASH,
            account=_account(),
            environment_variables=[],
            conversation_variables=[],
            session=session,
        )

    statement = session.scalar.call_args.args[0]
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_signal_receiver_failure_is_best_effort_after_atomic_commit(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    workflow_service_type.return_value = _workflow_service()
    monkeypatch.setattr(
        apply_module.app_draft_workflow_was_synced,
        "send",
        MagicMock(side_effect=RuntimeError("receiver failed")),
    )

    result = _apply(sqlite_session)

    assert result == {"hash": NEXT_HASH}
    sqlite_session.refresh(conversation)
    assert conversation.draft_hash == NEXT_HASH
    assert conversation.candidate_graph is None
    assert conversation.completion_run_id is None


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_conflict_uses_lightweight_reconciliation_without_copying_candidate(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_base_hash = "c" * 64
    sqlite_session.commit()
    workflow_service_type.return_value = _workflow_service()
    monkeypatch.setattr(
        apply_module.WorkflowAssistRunEventService,
        "get_candidate",
        MagicMock(side_effect=AssertionError("must not load candidate graph")),
    )

    with pytest.raises(apply_module.WorkflowAssistApplyConflictError):
        _apply(sqlite_session)
