from types import SimpleNamespace

from services.workflow_assist.agent_initializer import _candidate_state
from services.workflow_assist.protocol_rollout import protocol_for_new_conversation


def test_disabled_and_internal_rollout_keep_public_conversations_legacy() -> None:
    assert protocol_for_new_conversation("disabled") is None
    assert protocol_for_new_conversation("internal_samples") is None


def test_new_conversation_and_later_stages_enable_contract_protocol() -> None:
    assert protocol_for_new_conversation("new_conversations") == 1
    assert protocol_for_new_conversation("local_edits") == 1
    assert protocol_for_new_conversation("default") == 1


def test_candidate_restore_uses_frozen_run_protocol_not_mutable_conversation_value() -> None:
    conversation = SimpleNamespace(
        state={},
        candidate_revision=2,
        candidate_base_hash="b" * 64,
        compacted_until_sequence=None,
        compacted_state=None,
        contract_protocol_version=None,
        contract_revision=1,
        contract_hash="c" * 64,
        candidate_graph=None,
        workflow_contract={"protocol_version": 1},
    )

    frozen = _candidate_state(conversation, contract_protocol_version=1)
    disabled = _candidate_state(conversation, contract_protocol_version=None)

    assert frozen["contract_protocol_version"] == 1
    assert frozen["workflow_contract"] == {"protocol_version": 1}
    assert disabled["contract_protocol_version"] is None
    assert "workflow_contract" not in disabled
