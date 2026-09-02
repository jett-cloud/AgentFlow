from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

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
from services.errors.app import WorkflowHashNotEqualError
from services.workflow_assist import apply as apply_module
from services.workflow_assist import chat as chat_module
from services.workflow_assist import service as service_module
from services.workflow_assist.conversations import WorkflowAssistConversationNotFound, WorkflowAssistConversationService
from services.workflow_assist.run_coordinator import RunCoordinator
from services.workflow_assist.run_types import CandidateMutation, CommitStepOutcome, RunOwner
from services.workflow_assist.service import WorkflowAssistService
from services.workflow_service import WorkflowService

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
    "nodes": [{"id": "server-node", "data": {"type": "start"}}],
    "edges": [],
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
    session.commit()
    return conversation, run


def _workflow_service(draft_hash: str = BASE_HASH) -> MagicMock:
    service = MagicMock()
    service.get_draft_workflow.return_value = SimpleNamespace(
        unique_hash=draft_hash,
        features_dict={"opening_statement": "Welcome"},
        environment_variables=["environment-variable"],
        conversation_variables=["conversation-variable"],
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


@pytest.mark.parametrize("sqlite_session", [TABLES], indirect=True)
@patch("services.workflow_assist.apply.WorkflowService")
def test_apply_lays_out_linear_nodes_and_container_children(
    workflow_service_type: MagicMock,
    sqlite_session: Session,
) -> None:
    conversation, _run = _seed_completed_candidate(sqlite_session)
    conversation.candidate_graph = {
        "nodes": [
            {"id": "start", "data": {"type": "start", "title": "开始", "variables": []}},
            {"id": "kb_retrieval", "data": {"type": "knowledge-retrieval", "title": "检索"}},
            {"id": "llm", "data": {"type": "llm", "title": "生成答案"}},
            {"id": "end", "data": {"type": "end", "title": "结束"}},
            {"id": "loop1", "data": {"type": "loop", "title": "循环"}},
            {
                "id": "loop1start",
                "type": "custom-loop-start",
                "parentId": "loop1",
                "data": {"type": "loop-start"},
            },
            {"id": "loop_body", "parentId": "loop1", "data": {"type": "code"}},
        ],
        "edges": [
            {"source": "start", "target": "kb_retrieval"},
            {"source": "kb_retrieval", "target": "llm"},
            {"source": "llm", "target": "end"},
            {"source": "loop1start", "target": "loop_body"},
        ],
    }
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
            {"id": "start", "data": {"type": "start"}},
            {"id": "terminal", "data": {"type": "end"}},
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
            {"id": "start", "data": {"type": "start"}},
            {"id": "answer", "data": {"type": "end"}},
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
