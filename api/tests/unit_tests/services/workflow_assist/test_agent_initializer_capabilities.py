from types import SimpleNamespace
from unittest.mock import MagicMock

from services.workflow_assist import agent_initializer


class _ScalarResult:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def all(self) -> list[str]:
        return list(self._values)


def test_human_input_capability_snapshot_exposes_ids_without_member_details(monkeypatch) -> None:
    session = MagicMock()
    session.scalars.return_value = _ScalarResult(["member-2", "member-1"])
    monkeypatch.setattr(agent_initializer.dify_config, "MAIL_TYPE", "smtp")
    monkeypatch.setattr(
        agent_initializer.FeatureService,
        "get_features",
        lambda *_args, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    capabilities, member_ids = agent_initializer._human_input_capability_snapshot("tenant-1", session)

    assert capabilities == frozenset({"webapp", "email"})
    assert member_ids == frozenset({"member-1", "member-2"})
    session.scalars.assert_called_once()


def test_human_input_capability_snapshot_skips_member_query_when_email_is_unavailable(monkeypatch) -> None:
    session = MagicMock()
    monkeypatch.setattr(agent_initializer.dify_config, "MAIL_TYPE", None)
    monkeypatch.setattr(
        agent_initializer.FeatureService,
        "get_features",
        lambda *_args, **_kwargs: SimpleNamespace(human_input_email_delivery_enabled=True),
    )

    capabilities, member_ids = agent_initializer._human_input_capability_snapshot("tenant-1", session)

    assert capabilities == frozenset({"webapp"})
    assert member_ids == frozenset()
    session.scalars.assert_not_called()


def test_human_input_capability_snapshot_fails_closed_when_product_policy_cannot_load(monkeypatch) -> None:
    session = MagicMock()
    monkeypatch.setattr(agent_initializer.dify_config, "MAIL_TYPE", "smtp")
    monkeypatch.setattr(
        agent_initializer.FeatureService,
        "get_features",
        MagicMock(side_effect=RuntimeError("billing unavailable")),
    )

    capabilities, member_ids = agent_initializer._human_input_capability_snapshot("tenant-1", session)

    assert capabilities is None
    assert member_ids is None


def test_draft_conversation_metadata_exposes_types_and_excludes_secret_from_writable(monkeypatch) -> None:
    draft = SimpleNamespace(
        _conversation_variables=(
            '{"summary":{"name":"summary","value_type":"string","value":"private"},'
            '"token":{"name":"token","value_type":"secret","value":"must-not-leak"}}'
        )
    )
    service = SimpleNamespace(get_draft_workflow=lambda **_kwargs: draft)
    monkeypatch.setattr(agent_initializer, "WorkflowService", lambda: service)

    types, writable = agent_initializer._draft_conversation_variable_metadata(SimpleNamespace(id="app-1"), MagicMock())

    assert types == {"summary": "string", "token": "secret"}
    assert writable == frozenset({"summary"})
    assert "private" not in str(types)
    assert "must-not-leak" not in str(types)
