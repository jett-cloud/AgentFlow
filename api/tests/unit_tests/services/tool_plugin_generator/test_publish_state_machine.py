from datetime import UTC, datetime
from time import monotonic

import pytest

from services.tool_plugin_generator.publish_state_machine import PublishAttempt, PublishState


def test_publish_attempt_accepts_the_staged_publish_path() -> None:
    attempt = PublishAttempt(publish_mode="test")

    for state in (
        PublishState.PREFLIGHT,
        PublishState.STAGE_CLEANUP,
        PublishState.STAGE_INSTALL,
        PublishState.STAGE_VERIFY,
        PublishState.CLEANUP,
        PublishState.COMMIT_INSTALL,
        PublishState.PERSIST,
        PublishState.PUBLISHED,
    ):
        attempt.transition(state)

    assert attempt.terminal is True
    assert attempt.state is PublishState.PUBLISHED


def test_publish_attempt_rejects_skipped_or_post_terminal_transitions() -> None:
    attempt = PublishAttempt(publish_mode="direct")

    with pytest.raises(ValueError, match="Invalid publish transition"):
        attempt.transition(PublishState.COMMIT_INSTALL)

    attempt.transition(PublishState.FAILED)
    with pytest.raises(ValueError, match="terminal publish attempt"):
        attempt.transition(PublishState.PREFLIGHT)


def test_stage_results_are_generated_from_execution_timing() -> None:
    attempt = PublishAttempt(publish_mode="direct")
    started_at = datetime.now(UTC)
    started_monotonic = monotonic()

    result = attempt.record_stage(
        PublishState.PREPARING,
        started_monotonic=started_monotonic,
        started_at=started_at,
        details={"source": "draft"},
    )

    trace = attempt.to_trace()
    assert result.duration_ms >= 0
    assert trace["attempt_id"] == attempt.attempt_id
    assert trace["stages"] == [result.to_dict()]
    assert trace["stages"][0]["details"] == {"source": "draft"}


def test_execute_stage_records_failed_stage_before_reraising() -> None:
    attempt = PublishAttempt(publish_mode="test")

    with pytest.raises(RuntimeError, match="broken"):
        with attempt.execute_stage(PublishState.PREPARING):
            raise RuntimeError("broken")

    assert attempt.stages[0].stage == "preparing"
    assert attempt.stages[0].status == "failed"


def test_every_declared_transition_is_accepted() -> None:
    for source in PublishState:
        for target in PublishAttempt.allowed_targets(source):
            attempt = PublishAttempt(publish_mode="test", state=source)
            attempt.transition(target)
            assert attempt.state is target


def test_every_undeclared_transition_is_rejected() -> None:
    for source in PublishState:
        for target in PublishState:
            if target in PublishAttempt.allowed_targets(source):
                continue
            attempt = PublishAttempt(publish_mode="test", state=source)
            with pytest.raises(ValueError):
                attempt.transition(target)


def test_transition_hooks_can_persist_progress_and_stop_before_side_effect_boundary() -> None:
    traces: list[dict] = []

    def before_transition(target: PublishState) -> None:
        if target is PublishState.STAGE_INSTALL:
            raise RuntimeError("cancelled")

    attempt = PublishAttempt(
        publish_mode="test",
        before_transition=before_transition,
        on_change=traces.append,
    )
    attempt.transition(PublishState.PREFLIGHT)
    attempt.transition(PublishState.STAGE_CLEANUP)

    with pytest.raises(RuntimeError, match="cancelled"):
        attempt.transition(PublishState.STAGE_INSTALL)

    assert attempt.state is PublishState.STAGE_CLEANUP
    assert [trace["state"] for trace in traces] == ["preflight", "stage_cleanup"]
