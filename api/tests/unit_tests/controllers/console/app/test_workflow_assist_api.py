from __future__ import annotations

from datetime import datetime
from inspect import getsource, unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from flask import Flask
from flask_restx import Api
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest

from controllers.console.app import workflow_assist as workflow_assist_module
from controllers.console.app.error import WorkflowAssistConversationWriteConflict
from models import App, AppMode
from services.workflow_assist import service as workflow_assist_service_module
from services.workflow_assist.conversations import WorkflowAssistConversationWriteConflictError
from services.workflow_assist.run_events import (
    CandidateSnapshot,
    EventEnvelope,
    RunPage,
    RunSummary,
    StreamStart,
    TimelinePage,
)
from services.workflow_assist.service import WorkflowAssistService


def _app_model() -> App:
    app_model = MagicMock(spec=App)
    app_model.id = "app-1"
    app_model.tenant_id = "tenant-1"
    app_model.mode = AppMode.WORKFLOW
    return app_model


def _account():
    account = MagicMock()
    account.id = "account-1"
    return account


def _run_summary() -> RunSummary:
    return RunSummary(
        run_id="run-1",
        epoch=1,
        status="running",
        mode="workflow",
        candidate_revision=2,
        attempt=1,
        selected_node=None,
        queued_at=datetime(2026, 8, 25, 0, 0, 0),
        started_at=datetime(2026, 8, 25, 0, 0, 1),
        finished_at=None,
        termination_reason=None,
    )


@pytest.mark.parametrize(
    "resource_class",
    [
        workflow_assist_module.WorkflowAssistHydrateBindingsApi,
        workflow_assist_module.WorkflowAssistApplyApi,
    ],
)
def test_session_backed_workflow_assist_handlers_inject_session_before_account(resource_class: type) -> None:
    source = getsource(resource_class)

    assert source.index("@with_current_user") < source.index("@with_session") < source.index("@get_app_model")


@pytest.mark.parametrize(
    ("query_model", "payload"),
    [
        ("WorkflowAssistRunListQuery", {"after_epoch": -1}),
        ("WorkflowAssistRunListQuery", {"limit": 101}),
        ("WorkflowAssistTimelineQuery", {"after_sequence": -1}),
        ("WorkflowAssistTimelineQuery", {"limit": 501}),
        ("WorkflowAssistRunEventsQuery", {"after": -1}),
    ],
)
def test_v2_read_query_models_reject_invalid_cursors_and_limits(query_model: str, payload: dict[str, int]) -> None:
    model = getattr(workflow_assist_module, query_model)

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_run_list_controller_serializes_metadata_without_event_payloads(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = workflow_assist_module.WorkflowAssistRunListApi()
    method = unwrap(api.get)
    service = MagicMock()
    service.list_runs.return_value = RunPage(items=(_run_summary(),), has_more=False, next_after_epoch=1)
    monkeypatch.setattr(workflow_assist_module, "WorkflowAssistRunEventService", lambda _session: service)

    with app.test_request_context("/?after_epoch=0&limit=50"):
        response = method(
            api,
            MagicMock(),
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
        )

    assert response["has_more"] is False
    assert response["next_after_epoch"] == 1
    assert response["items"][0]["run_id"] == "run-1"
    assert "events" not in response["items"][0]


@pytest.mark.parametrize("compact", [False, True])
def test_timeline_controller_serializes_v2_envelopes_and_tuple_cursor(
    app: Flask, monkeypatch: pytest.MonkeyPatch, compact: bool
) -> None:
    api = workflow_assist_module.WorkflowAssistTimelineApi()
    method = unwrap(api.get)
    event = EventEnvelope(
        event="user.message",
        run_id="run-1",
        epoch=1,
        sequence=0,
        step_id="user:run-1",
        created_at=datetime(2026, 8, 25, 0, 0, 0),
        data={"text": "Build it"},
    )
    service = MagicMock()
    service.timeline.return_value = TimelinePage(items=(event,), has_more=False, cursor_epoch=1, cursor_sequence=0)
    monkeypatch.setattr(workflow_assist_module, "WorkflowAssistRunEventService", lambda _session: service)

    with app.test_request_context(f"/?after_epoch=0&after_sequence=0&limit=200&compact={str(compact).lower()}"):
        response = method(
            api,
            MagicMock(),
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
        )

    assert response == {
        "items": [event.as_dict()],
        "has_more": False,
        "cursor": {"epoch": 1, "sequence": 0},
    }
    assert service.timeline.call_args.kwargs["compact"] is compact


def test_candidate_controller_returns_server_owned_reconciliation_snapshot(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = workflow_assist_module.WorkflowAssistCandidateApi()
    method = unwrap(api.get)
    service = MagicMock()
    service.get_candidate.return_value = CandidateSnapshot(
        graph={"nodes": [], "edges": []},
        revision=2,
        base_hash="base",
        completion_evidence=None,
        contract_report=None,
        active_run=_run_summary(),
        latest_run=_run_summary(),
    )
    monkeypatch.setattr(workflow_assist_module, "WorkflowAssistRunEventService", lambda _session: service)

    with app.test_request_context("/"):
        response = method(
            api,
            MagicMock(),
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
        )

    assert response["graph"] == {"nodes": [], "edges": []}
    assert response["revision"] == 2
    assert response["active_run"]["run_id"] == "run-1"


def test_events_controller_prefers_last_event_id_and_emits_replayable_sse(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_after: list[int] = []

    class FakeStream:
        def __init__(self, **kwargs):
            observed_after.append(kwargs["after"])

        def start(self) -> StreamStart:
            return StreamStart(events=(), terminal=False)

        def iter_chunks(self, _start: StreamStart):
            yield ": heartbeat\n\n"

    monkeypatch.setattr(workflow_assist_module, "WorkflowAssistRunEventStream", FakeStream)
    api = workflow_assist_module.WorkflowAssistRunEventsApi()
    method = unwrap(api.get)

    with app.test_request_context("/?after=2", headers={"Last-Event-ID": "7"}):
        response = method(
            api,
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        )
        body = response.get_data(as_text=True)

    assert observed_after == [7]
    assert response.mimetype == "text/event-stream"
    assert body == ": heartbeat\n\n"


def test_events_controller_returns_truly_empty_204_for_terminal_replay_boundary(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = MagicMock()
    stream.start.return_value = StreamStart(events=(), terminal=True)
    monkeypatch.setattr(workflow_assist_module, "WorkflowAssistRunEventStream", lambda **_kwargs: stream)
    api = workflow_assist_module.WorkflowAssistRunEventsApi()
    method = unwrap(api.get)

    with app.test_request_context("/?after=9"):
        response = method(
            api,
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        )

    assert response.status_code == 204
    assert response.get_data() == b""
    stream.iter_chunks.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "Build it", "mode": "workflow", "model_config": {}, "graph": {}},
        {"message": "Build it", "mode": "workflow", "model_config": {}, "draft_hash": "a" * 64},
        {"message": "Build it", "mode": "workflow", "model_config": {}, "candidate_hash": "a" * 64},
        {"message": "Build it", "mode": "workflow", "model_config": {}, "unknown": True},
    ],
)
def test_turn_payload_forbids_every_non_v2_field(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        workflow_assist_module.WorkflowAssistTurnPayload.model_validate(payload)


def test_turn_payload_accepts_only_the_exact_v2_shape() -> None:
    parsed = workflow_assist_module.WorkflowAssistTurnPayload.model_validate(
        {
            "message": "Build it",
            "mode": "advanced-chat",
            "model_config": {"provider": "openai"},
            "selected_node": "node-1",
        }
    )

    assert parsed.model_dump(by_alias=True) == {
        "message": "Build it",
        "mode": "advanced-chat",
        "model_config": {"provider": "openai"},
        "selected_node": "node-1",
        "references": None,
        "live_acceptance_request_id": None,
    }


def test_turn_payload_drops_malformed_references_and_rejects_more_than_eight() -> None:
    parsed = workflow_assist_module.WorkflowAssistTurnPayload.model_validate(
        {
            "message": "Build it",
            "mode": "workflow",
            "model_config": {},
            "references": [
                {"kind": "node", "id": "n1", "label": "知识库检索"},
                {"kind": "bad"},
            ],
        }
    )
    assert parsed.references == [{"kind": "node", "id": "n1", "label": "知识库检索"}]

    with pytest.raises(ValidationError):
        workflow_assist_module.WorkflowAssistTurnPayload.model_validate(
            {
                "message": "Build it",
                "mode": "workflow",
                "model_config": {},
                "references": [{"kind": "node", "id": f"n{index}"} for index in range(9)],
            }
        )


@pytest.mark.parametrize("payload", [{}, {"epoch": 1, "force": True}, {"epoch": 0}, {"epoch": "one"}])
def test_abort_payload_requires_only_a_positive_integer_epoch(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        workflow_assist_module.WorkflowAssistAbortPayload.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"conversation_id": "00000000-0000-0000-0000-000000000001", "hash": "A" * 64},
        {"conversation_id": "00000000-0000-0000-0000-000000000001", "hash": "a" * 63},
        {"conversation_id": "00000000-0000-0000-0000-000000000001", "hash": "g" * 64},
        {
            "conversation_id": "00000000-0000-0000-0000-000000000001",
            "hash": "a" * 64,
            "graph": {"nodes": [], "edges": []},
        },
        {"conversation_id": "00000000-0000-0000-0000-000000000001", "hash": "a" * 64, "force": True},
        {
            "conversation_id": "00000000-0000-0000-0000-000000000001",
            "hash": "a" * 64,
            "candidate_revision": 1,
        },
    ],
)
def test_apply_payload_forbids_invalid_hashes_and_legacy_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        workflow_assist_module.ApplyPayload.model_validate(payload)


def test_turn_controller_returns_exact_202_contract(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    run = SimpleNamespace(id="run-1", epoch=7)
    start_turn = MagicMock(return_value=run)
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "start_turn", start_turn)
    api = workflow_assist_module.WorkflowAssistTurnApi()
    method = unwrap(api.post)
    conversation_id = UUID("00000000-0000-0000-0000-000000000001")

    with app.test_request_context(
        "/",
        method="POST",
        json={
            "message": "Build it",
            "mode": "workflow",
            "model_config": {"provider": "openai"},
            "selected_node": "node-1",
        },
    ):
        response, status = method(api, MagicMock(), _account(), _app_model(), conversation_id)

    assert status == 202
    assert response == {"conversation_id": str(conversation_id), "run_id": "run-1", "epoch": 7, "cursor": 0}
    start_turn.assert_called_once_with(
        session=start_turn.call_args.kwargs["session"],
        app_model=start_turn.call_args.kwargs["app_model"],
        account=start_turn.call_args.kwargs["account"],
        conversation_id=str(conversation_id),
        message="Build it",
        mode="workflow",
        model_config={"provider": "openai"},
        selected_node="node-1",
        references=None,
        live_acceptance_request_id=None,
    )


def test_start_turn_commits_before_enqueue_and_passes_full_owner_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    session = MagicMock()
    session.commit.side_effect = lambda: order.append("commit")
    run = SimpleNamespace(id="run-1", epoch=3)
    coordinator = MagicMock()
    coordinator.start_turn.return_value = run
    monkeypatch.setattr(workflow_assist_service_module, "RunCoordinator", lambda _session: coordinator)
    monkeypatch.setattr(WorkflowAssistService, "dispatch_run", lambda _run: order.append("enqueue"))
    monkeypatch.setattr(WorkflowAssistService, "_freeze_turn_draft", MagicMock(), raising=False)

    result = WorkflowAssistService.start_turn(
        session=session,
        app_model=SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow"),
        account=SimpleNamespace(id="account-1"),
        conversation_id="conversation-1",
        message="Build it",
        mode="workflow",
        model_config={"provider": "openai"},
        selected_node=None,
    )

    assert result is run
    assert order == ["commit", "enqueue"]
    owner = coordinator.start_turn.call_args.kwargs["owner"]
    assert (owner.tenant_id, owner.app_id, owner.account_id, owner.conversation_id) == (
        "tenant-1",
        "app-1",
        "account-1",
        "conversation-1",
    )


def test_start_turn_rejects_a_mode_that_does_not_match_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = MagicMock()
    monkeypatch.setattr(workflow_assist_service_module, "RunCoordinator", lambda _session: coordinator)

    with pytest.raises(ValueError, match="mode"):
        WorkflowAssistService.start_turn(
            session=MagicMock(),
            app_model=SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="advanced-chat"),
            account=SimpleNamespace(id="account-1"),
            conversation_id="conversation-1",
            message="Build it",
            mode="workflow",
            model_config={},
        )

    coordinator.start_turn.assert_not_called()


def test_start_turn_rejects_unknown_node_tool_and_dataset_references(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator = MagicMock()
    monkeypatch.setattr(workflow_assist_service_module, "RunCoordinator", lambda _session: coordinator)
    monkeypatch.setattr(
        WorkflowAssistService,
        "_freeze_turn_draft",
        lambda **_kwargs: SimpleNamespace(graph_dict={"nodes": [{"id": "n1"}], "edges": []}),
        raising=False,
    )
    monkeypatch.setattr(workflow_assist_service_module, "build_tool_catalogue", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(workflow_assist_service_module, "build_knowledge_catalogue", lambda *_args, **_kwargs: [])

    def start(references: list[dict[str, object]]) -> None:
        WorkflowAssistService.start_turn(
            session=MagicMock(),
            app_model=SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow"),
            account=SimpleNamespace(id="account-1"),
            conversation_id="conversation-1",
            message="Build it",
            mode="workflow",
            model_config={},
            references=references,
        )

    with pytest.raises(workflow_assist_service_module.WorkflowAssistInvalidTurnError, match="unknown referenced node"):
        start([{"kind": "node", "id": "missing", "label": "Gone"}])
    with pytest.raises(workflow_assist_service_module.WorkflowAssistInvalidTurnError, match="unknown referenced tool"):
        start(
            [
                {
                    "kind": "tool",
                    "id": "time/current_time",
                    "label": "当前时间",
                    "provider": "time",
                    "tool_name": "current_time",
                }
            ]
        )
    with pytest.raises(
        workflow_assist_service_module.WorkflowAssistInvalidTurnError, match="unknown referenced dataset"
    ):
        start([{"kind": "dataset", "id": "ds-missing", "label": "产品文档"}])
    coordinator.start_turn.assert_not_called()


@pytest.mark.parametrize("message", ["   ", "你" * 21846], ids=["whitespace", "utf8-over-64k"])
def test_turn_controller_translates_invalid_message_to_http_400(app: Flask, message: str) -> None:
    api = workflow_assist_module.WorkflowAssistTurnApi()
    method = unwrap(api.post)

    with app.test_request_context(
        "/",
        method="POST",
        json={"message": message, "mode": "workflow", "model_config": {}},
    ):
        with pytest.raises(BadRequest) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
            )

    assert raised.value.code == 400


def test_turn_controller_translates_app_mode_mismatch_to_http_400(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_turn = workflow_assist_service_module.WorkflowAssistInvalidTurnError("mode mismatch")
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "start_turn",
        MagicMock(side_effect=invalid_turn),
    )
    api = workflow_assist_module.WorkflowAssistTurnApi()
    method = unwrap(api.post)

    with app.test_request_context(
        "/",
        method="POST",
        json={"message": "Build it", "mode": "workflow", "model_config": {}},
    ):
        with pytest.raises(BadRequest) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
            )

    assert raised.value.code == 400


def test_turn_controller_translates_unknown_references_to_http_400(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "start_turn",
        MagicMock(
            side_effect=workflow_assist_service_module.WorkflowAssistInvalidTurnError(
                "unknown referenced node 'missing'"
            )
        ),
    )
    api = workflow_assist_module.WorkflowAssistTurnApi()
    method = unwrap(api.post)

    with app.test_request_context(
        "/",
        method="POST",
        json={
            "message": "Build it",
            "mode": "workflow",
            "model_config": {},
            "references": [{"kind": "node", "id": "missing", "label": "Gone"}],
        },
    ):
        with pytest.raises(BadRequest) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
            )

    assert raised.value.code == 400


def test_turn_controller_translates_conversation_write_conflict_to_http_409(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "start_turn",
        MagicMock(side_effect=WorkflowAssistConversationWriteConflictError("concurrent turn")),
    )
    api = workflow_assist_module.WorkflowAssistTurnApi()
    method = unwrap(api.post)

    with app.test_request_context(
        "/",
        method="POST",
        json={"message": "Build it", "mode": "workflow", "model_config": {}},
    ):
        with pytest.raises(WorkflowAssistConversationWriteConflict) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
            )

    assert raised.value.data == {
        "code": "CONVERSATION_WRITE_CONFLICT",
        "message": "Workflow Assist conversation was updated concurrently. Please retry.",
        "status": 409,
    }


def test_start_turn_never_dispatches_when_database_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.commit.side_effect = RuntimeError("commit failed")
    coordinator = MagicMock()
    coordinator.start_turn.return_value = SimpleNamespace(id="run-1", epoch=1)
    dispatch = MagicMock()
    monkeypatch.setattr(workflow_assist_service_module, "RunCoordinator", lambda _session: coordinator)
    monkeypatch.setattr(WorkflowAssistService, "dispatch_run", dispatch)
    monkeypatch.setattr(WorkflowAssistService, "_freeze_turn_draft", MagicMock(), raising=False)

    with pytest.raises(RuntimeError, match="commit failed"):
        WorkflowAssistService.start_turn(
            session=session,
            app_model=SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow"),
            account=SimpleNamespace(id="account-1"),
            conversation_id="conversation-1",
            message="Build it",
            mode="workflow",
            model_config={},
        )

    dispatch.assert_not_called()


def test_abort_controller_returns_current_run_conflict_snapshot(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _run_summary()
    result = SimpleNamespace(aborted=False, active_run=summary, latest_run=summary)
    abort_run = MagicMock(return_value=result)
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "abort_run", abort_run)
    api = workflow_assist_module.WorkflowAssistRunAbortApi()
    method = unwrap(api.post)

    with app.test_request_context("/", method="POST", json={"epoch": 4}):
        response, status = method(
            api,
            MagicMock(),
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        )

    assert status == 409
    assert response["active_run"]["run_id"] == "run-1"
    assert response["latest_run"]["epoch"] == 1


def test_abort_controller_returns_success_for_the_fenced_run(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    result = SimpleNamespace(aborted=True, active_run=None, latest_run=_run_summary())
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "abort_run", MagicMock(return_value=result))
    api = workflow_assist_module.WorkflowAssistRunAbortApi()
    method = unwrap(api.post)

    with app.test_request_context("/", method="POST", json={"epoch": 1}):
        response = method(
            api,
            MagicMock(),
            _account(),
            _app_model(),
            UUID("00000000-0000-0000-0000-000000000001"),
            UUID("00000000-0000-0000-0000-000000000002"),
        )

    assert response == {"run_id": "00000000-0000-0000-0000-000000000002", "epoch": 1, "status": "aborted"}


def test_abort_controller_translates_conversation_write_conflict_to_http_409(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "abort_run",
        MagicMock(side_effect=WorkflowAssistConversationWriteConflictError("concurrent abort")),
    )
    api = workflow_assist_module.WorkflowAssistRunAbortApi()
    method = unwrap(api.post)

    with app.test_request_context("/", method="POST", json={"epoch": 1}):
        with pytest.raises(WorkflowAssistConversationWriteConflict) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
                UUID("00000000-0000-0000-0000-000000000002"),
            )

    assert raised.value.data == {
        "code": "CONVERSATION_WRITE_CONFLICT",
        "message": "Workflow Assist conversation was updated concurrently. Please retry.",
        "status": 409,
    }


def test_apply_controller_passes_only_server_lookup_coordinates(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    apply = MagicMock(return_value={"hash": "b" * 64})
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "apply", apply)
    api = workflow_assist_module.WorkflowAssistApplyApi()
    method = unwrap(api.post)
    conversation_id = "00000000-0000-0000-0000-000000000001"

    with app.test_request_context("/", method="POST", json={"conversation_id": conversation_id, "hash": "a" * 64}):
        response = method(api, MagicMock(), _account(), _app_model())

    assert response == {"hash": "b" * 64}
    assert apply.call_args.kwargs["conversation_id"] == conversation_id
    assert apply.call_args.kwargs["unique_hash"] == "a" * 64
    assert "graph" not in apply.call_args.kwargs


def test_apply_controller_returns_authoritative_409_reconciliation(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _run_summary()
    conflict = workflow_assist_module.WorkflowAssistApplyConflictError(
        "stale candidate",
        active_run=summary,
        latest_run=summary,
    )
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "apply",
        MagicMock(side_effect=conflict),
    )
    api = workflow_assist_module.WorkflowAssistApplyApi()
    method = unwrap(api.post)

    with app.test_request_context(
        "/",
        method="POST",
        json={"conversation_id": "00000000-0000-0000-0000-000000000001", "hash": "a" * 64},
    ):
        response, status = method(api, MagicMock(), _account(), _app_model())

    assert status == 409
    assert set(response) == {"active_run", "latest_run"}
    assert response["active_run"]["run_id"] == "run-1"
    assert response["latest_run"]["status"] == "running"


def test_apply_success_response_is_registered_and_exact(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "apply",
        MagicMock(return_value={"hash": "b" * 64}),
    )
    api = workflow_assist_module.WorkflowAssistApplyApi()
    method = unwrap(api.post)

    with app.test_request_context(
        "/",
        method="POST",
        json={"conversation_id": "00000000-0000-0000-0000-000000000001", "hash": "a" * 64},
    ):
        response = method(api, MagicMock(), _account(), _app_model())

    assert response == {"hash": "b" * 64}
    assert workflow_assist_module.WorkflowAssistApplyResponse.__name__ in workflow_assist_module.console_ns.models


def test_removed_legacy_write_routes_cannot_reach_mutation_services(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = MagicMock()
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistConversationService, "update", update)
    app_id = "00000000-0000-0000-0000-000000000010"
    conversation_id = "00000000-0000-0000-0000-000000000011"
    route_app = Flask("workflow-assist-removed-routes")
    Api(route_app).add_namespace(workflow_assist_module.console_ns, path="/console/api")
    client = route_app.test_client()

    stream = client.post(
        f"/console/api/apps/{app_id}/workflow-assist/chat/stream",
        json={"conversation_id": conversation_id, "message": "mutate"},
    )
    patch_response = client.patch(
        f"/console/api/apps/{app_id}/workflow-assist/conversations/{conversation_id}",
        json={"draft_hash": "a" * 32, "state": {"candidate_graph": {"nodes": []}}},
    )

    assert stream.status_code == 404
    assert patch_response.status_code == 405
    update.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Invoice review", "draft_hash": "a" * 64},
        {"title": "Invoice review", "state": {"candidate_graph": {"nodes": []}}},
        {"title": "Invoice review", "graph": {}},
        {"title": "   "},
        {},
    ],
)
def test_conversation_title_payload_forbids_graph_writes_and_blank_titles(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        workflow_assist_module.WorkflowAssistConversationTitlePayload.model_validate(payload)


def test_conversation_title_controller_updates_title_only(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    conversation_id = UUID("00000000-0000-0000-0000-000000000001")
    conversation = SimpleNamespace(
        id=str(conversation_id),
        title="Invoice review",
        draft_hash=None,
        created_at=datetime(2026, 8, 25, 0, 0, 0),
        updated_at=datetime(2026, 8, 25, 0, 0, 1),
        state={"session": {"phase": "await_apply"}},
    )
    update = MagicMock(return_value=conversation)
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistConversationService, "update", update)
    api = workflow_assist_module.WorkflowAssistConversationTitleApi()
    method = unwrap(api.patch)

    with app.test_request_context("/", method="PATCH", json={"title": "  Invoice review  "}):
        response = method(api, MagicMock(), _account(), _app_model(), conversation_id)

    assert response["id"] == str(conversation_id)
    assert response["title"] == "Invoice review"
    assert "state" not in response
    assert update.call_args.kwargs["title"] == "Invoice review"
    assert "draft_hash" not in update.call_args.kwargs
    assert "state" not in update.call_args.kwargs


def test_retry_controller_returns_exact_202_contract(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    run = SimpleNamespace(id="run-2", epoch=8)
    retry_run = MagicMock(return_value=run)
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "retry_run", retry_run)
    api = workflow_assist_module.WorkflowAssistRunRetryApi()
    method = unwrap(api.post)
    conversation_id = UUID("00000000-0000-0000-0000-000000000001")
    run_id = UUID("00000000-0000-0000-0000-000000000002")

    with app.test_request_context("/", method="POST", json={"epoch": 7, "failed_step_id": "error:provider"}):
        response, status = method(api, MagicMock(), _account(), _app_model(), conversation_id, run_id)

    assert status == 202
    assert response == {"conversation_id": str(conversation_id), "run_id": "run-2", "epoch": 8, "cursor": 0}
    retry_run.assert_called_once_with(
        session=retry_run.call_args.kwargs["session"],
        app_model=retry_run.call_args.kwargs["app_model"],
        account=retry_run.call_args.kwargs["account"],
        conversation_id=str(conversation_id),
        run_id=str(run_id),
        epoch=7,
        failed_step_id="error:provider",
    )


def test_retry_controller_translates_non_retryable_step_to_http_400(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "retry_run",
        MagicMock(
            side_effect=workflow_assist_service_module.WorkflowAssistInvalidRetryError("failed step is not retryable")
        ),
    )
    api = workflow_assist_module.WorkflowAssistRunRetryApi()
    method = unwrap(api.post)

    with app.test_request_context("/", method="POST", json={"epoch": 1, "failed_step_id": "aborted:user_abort"}):
        with pytest.raises(BadRequest) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
                UUID("00000000-0000-0000-0000-000000000002"),
            )

    assert raised.value.code == 400


def test_retry_controller_translates_stale_epoch_to_http_409(
    app: Flask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow_assist_module.WorkflowAssistService,
        "retry_run",
        MagicMock(side_effect=WorkflowAssistConversationWriteConflictError("stale epoch")),
    )
    api = workflow_assist_module.WorkflowAssistRunRetryApi()
    method = unwrap(api.post)

    with app.test_request_context("/", method="POST", json={"epoch": 1, "failed_step_id": "error:provider"}):
        with pytest.raises(WorkflowAssistConversationWriteConflict) as raised:
            method(
                api,
                MagicMock(),
                _account(),
                _app_model(),
                UUID("00000000-0000-0000-0000-000000000001"),
                UUID("00000000-0000-0000-0000-000000000002"),
            )

    assert raised.value.data["status"] == 409


def test_retry_run_commits_before_enqueue_and_passes_full_owner_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    session = MagicMock()
    session.commit.side_effect = lambda: order.append("commit")
    run = SimpleNamespace(id="run-2", epoch=2)
    coordinator = MagicMock()
    coordinator.retry_failed_step.return_value = run
    monkeypatch.setattr(workflow_assist_service_module, "RunCoordinator", lambda _session: coordinator)
    monkeypatch.setattr(WorkflowAssistService, "dispatch_run", lambda _run: order.append("enqueue"))
    monkeypatch.setattr(WorkflowAssistService, "_freeze_turn_draft", MagicMock(), raising=False)

    result = WorkflowAssistService.retry_run(
        session=session,
        app_model=SimpleNamespace(id="app-1", tenant_id="tenant-1", mode="workflow"),
        account=SimpleNamespace(id="account-1"),
        conversation_id="conversation-1",
        run_id="run-1",
        epoch=1,
        failed_step_id="error:provider",
    )

    assert result is run
    assert order == ["commit", "enqueue"]
    owner = coordinator.retry_failed_step.call_args.kwargs["owner"]
    assert (owner.tenant_id, owner.app_id, owner.account_id, owner.conversation_id) == (
        "tenant-1",
        "app-1",
        "account-1",
        "conversation-1",
    )


def _validate_payload() -> dict[str, object]:
    return {
        "graph": {"nodes": [], "edges": []},
        "mode": "rebuild",
        "mutable_node_ids": [],
        "planned_new_ids": [],
        "intent_flags": {},
    }


def test_validate_controller_passes_workflow_generation_mode(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    validate = MagicMock(return_value={"ok": True, "errors": [], "warnings": []})
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "validate", validate)
    api = workflow_assist_module.WorkflowAssistValidateApi()
    method = unwrap(api.post)

    with app.test_request_context("/", method="POST", json=_validate_payload()):
        method(api, _app_model())

    assert validate.call_args.kwargs["generation_mode"] == "workflow"


def test_validate_controller_passes_advanced_chat_generation_mode(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    validate = MagicMock(return_value={"ok": True, "errors": [], "warnings": []})
    monkeypatch.setattr(workflow_assist_module.WorkflowAssistService, "validate", validate)
    api = workflow_assist_module.WorkflowAssistValidateApi()
    method = unwrap(api.post)
    app_model = _app_model()
    app_model.mode = AppMode.ADVANCED_CHAT

    with app.test_request_context("/", method="POST", json=_validate_payload()):
        method(api, app_model)

    assert validate.call_args.kwargs["generation_mode"] == "advanced-chat"
