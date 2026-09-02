from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.workflow.generator.llm_response import (
    LLMJsonClient,
    StageSchemaError,
    chunk_finish_reason,
    json_failure_detail,
    parse_stage_json,
)
from graphon.model_runtime.entities.llm_entities import LLMResultChunk, LLMResultChunkDelta
from graphon.model_runtime.entities.message_entities import AssistantPromptMessage
from graphon.model_runtime.errors.invoke import InvokeConnectionError


def _chunk(text: str, finish_reason: str | None = None) -> LLMResultChunk:
    return LLMResultChunk(
        model="gpt-4o",
        prompt_messages=[],
        delta=LLMResultChunkDelta(
            index=0,
            message=AssistantPromptMessage(content=text),
            finish_reason=finish_reason,
        ),
    )


def test_interrupted_stream_discards_partial_attempt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.workflow.generator.llm_response.time.sleep", lambda _seconds: None)
    attempts = 0

    def invoke_llm(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:

            def interrupted():
                yield _chunk('{"config":')
                raise InvokeConnectionError("connection reset")

            return interrupted()
        return iter([_chunk('{"config":{"variables":[]}}')])

    model = MagicMock()
    model.invoke_llm.side_effect = invoke_llm
    client = LLMJsonClient(model_instance=model, model_parameters={})

    result = client.invoke_json(messages=[], stage="Builder node1")

    assert result == {"config": {"variables": []}}


def test_parse_stage_json_prefers_payload_after_reasoning():
    assert parse_stage_json('<think>{"wrong":true}</think>{"right":true}') == {"right": True}


def test_json_failure_detail_distinguishes_empty_response():
    assert json_failure_detail("  ") == "empty model response (0 chars)"


def test_chunk_finish_reason_is_normalized():
    assert chunk_finish_reason(_chunk("", "MAX-TOKENS")) == "max_tokens"


def test_invoke_json_captures_provider_token_usage() -> None:
    model = MagicMock()
    model.invoke_llm.return_value = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=23, completion_tokens=7),
        message=SimpleNamespace(get_text_content=lambda: '{"ok":true}'),
    )
    client = LLMJsonClient(model_instance=model, model_parameters={})

    result = client.invoke_json(messages=[], stage="Planner")

    assert result == {"ok": True}
    assert client.last_usage == (23, 7)


from ._runner_test_support import (
    WorkflowGenerator,
    _GraphFixtureModel,
    _llm_chunk,
    _llm_result,
    _stream_text,
    _truncated_stream,
    dify_config,
    json,
    pytest,
)


class TestWorkflowGeneratorTransientRetry:
    """
    A single transient provider blip (connection drop, 503, rate-limit)
    used to kill the whole two-call generation. The runner now retries
    transient invoke errors with bounded backoff, while permanent errors
    (auth, bad-request) still fail fast so the user isn't billed for
    pointless retries against a misconfigured model.
    """

    @staticmethod
    def _planner() -> str:
        return json.dumps(
            {
                "title": "x",
                "description": "x",
                "nodes": [
                    {"label": "Start", "node_type": "start", "purpose": "x"},
                    {"label": "End", "node_type": "end", "purpose": "x"},
                ],
            }
        )

    @staticmethod
    def _builder() -> str:
        return json.dumps(
            {
                "nodes": [
                    {
                        "id": "node1",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "start", "title": "Start"},
                    },
                    {
                        "id": "node2",
                        "type": "custom",
                        "position": {"x": 0, "y": 0},
                        "data": {"type": "end", "title": "End"},
                    },
                ],
                "edges": [{"id": "x", "source": "node1", "target": "node2", "type": "custom"}],
                "viewport": {"x": 0, "y": 0, "zoom": 0.7},
            }
        )

    def test_retries_transient_invoke_error_then_succeeds(self, monkeypatch: pytest.MonkeyPatch):
        # The planner's first invoke raises a transient connection error; the
        # retry succeeds and the pipeline completes normally. Sleep is patched
        # out so the test doesn't actually wait for the backoff.
        import core.workflow.generator.llm_response as _runner_mod
        from graphon.model_runtime.errors.invoke import InvokeConnectionError

        monkeypatch.setattr(_runner_mod.time, "sleep", lambda _s: None)

        fixture_model = _GraphFixtureModel(self._planner(), self._builder())
        first_call = True

        def invoke_with_one_failure(**kwargs):
            nonlocal first_call
            if first_call:
                first_call = False
                raise InvokeConnectionError("connection reset")
            return fixture_model._invoke(**kwargs)

        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = invoke_with_one_failure

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["error"] == ""
        # Planner (failed once + retried) plus two node builders.
        assert model_instance.invoke_llm.call_count == 4

    def test_midstream_retry_discards_partial_attempt_before_parsing(self, monkeypatch: pytest.MonkeyPatch):
        import core.workflow.generator.llm_response as _runner_mod
        from graphon.model_runtime.errors.invoke import InvokeConnectionError

        monkeypatch.setattr(_runner_mod.time, "sleep", lambda _s: None)
        monkeypatch.setattr(dify_config, "WORKFLOW_GENERATOR_NODE_BUILDER_MAX_WORKERS", 1)
        fixture_model = _GraphFixtureModel(self._planner(), self._builder())
        interrupted = False

        def invoke_with_midstream_failure(**kwargs):
            nonlocal interrupted
            prompt = "\n".join(str(message.content) for message in kwargs["prompt_messages"])
            if "id=node1, type=start" in prompt and not interrupted:
                interrupted = True

                def partial_stream():
                    yield _llm_chunk('{"config":')
                    raise InvokeConnectionError("connection reset after first chunk")

                return partial_stream()
            return fixture_model._invoke(**kwargs)

        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = invoke_with_midstream_failure

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["error"] == ""
        start = next(node for node in result["graph"]["nodes"] if node["id"] == "node1")
        assert "config" not in start["data"]

    def test_gives_up_after_exhausting_transient_retries(self, monkeypatch: pytest.MonkeyPatch):
        # Every attempt hits the transient error — once we exhaust the retry
        # budget the failure surfaces as a normal error envelope rather than
        # hanging or looping forever.
        import core.workflow.generator.llm_response as _runner_mod
        from graphon.model_runtime.errors.invoke import InvokeServerUnavailableError

        monkeypatch.setattr(_runner_mod.time, "sleep", lambda _s: None)

        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = InvokeServerUnavailableError("503 from upstream")

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["error"]
        # Bounded: planner attempts == the retry budget, nothing more.
        from core.workflow.generator.llm_response import INVOKE_MAX_ATTEMPTS as _INVOKE_MAX_ATTEMPTS

        assert model_instance.invoke_llm.call_count == _INVOKE_MAX_ATTEMPTS

    def test_does_not_retry_permanent_invoke_error(self, monkeypatch: pytest.MonkeyPatch):
        # An auth error is permanent — retrying just burns latency and quota.
        # The runner must fail on the first attempt.
        # If the code wrongly slept here we'd want the test to still be fast;
        # patch sleep defensively so a regression can't hang CI.
        import core.workflow.generator.llm_response as _runner_mod
        from graphon.model_runtime.errors.invoke import InvokeAuthorizationError

        monkeypatch.setattr(_runner_mod.time, "sleep", lambda _s: None)

        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = InvokeAuthorizationError("bad key")

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert result["error"]
        assert model_instance.invoke_llm.call_count == 1


class TestJsonFailureDetail:
    """``_json_failure_detail`` must name the empty case and quote prose."""

    def test_blank_response_names_the_empty_case(self):
        from core.workflow.generator.llm_response import json_failure_detail as _json_failure_detail

        assert _json_failure_detail("   \n  ") == "empty model response (0 chars)"

    def test_prose_response_quotes_a_preview(self):
        from core.workflow.generator.llm_response import json_failure_detail as _json_failure_detail

        detail = _json_failure_detail("好的，我来帮你规划这个工作流。")
        assert "no JSON object in response" in detail
        assert "好的，我来帮你规划这个工作流。" in detail
        assert "(15 chars)" in detail

    def test_preview_collapses_whitespace_and_truncates(self):
        from core.workflow.generator.llm_response import json_failure_detail as _json_failure_detail

        detail = _json_failure_detail("first line\n\n   second line" + "x" * 500)
        assert "first line second line" in detail
        assert detail.endswith('…"')
        assert "x" * 201 not in detail


class TestParseStageJson:
    """``_parse_stage_json`` recovers the response shapes json_repair alone rejects."""

    def test_plain_object_parses(self):
        from core.workflow.generator.llm_response import parse_stage_json as _parse_stage_json

        assert _parse_stage_json('{"nodes": []}') == {"nodes": []}

    def test_reasoning_block_is_stripped_before_parsing(self):
        from core.workflow.generator.llm_response import parse_stage_json as _parse_stage_json

        raw = '<think>先看看用户想要什么 {不是JSON}</think>\n{"nodes": [1]}'
        assert _parse_stage_json(raw) == {"nodes": [1]}

    def test_unclosed_reasoning_block_leaves_nothing_to_parse(self):
        from core.workflow.generator.llm_response import parse_stage_json as _parse_stage_json

        assert _parse_stage_json("<think>思考被 max_tokens 截断了，还没开始输出") is None

    def test_duplicated_objects_take_the_richest_one(self):
        from core.workflow.generator.llm_response import parse_stage_json as _parse_stage_json

        raw = '{"nodes": []}{"nodes": [1], "edges": [2], "title": "t"}'
        assert _parse_stage_json(raw) == {"nodes": [1], "edges": [2], "title": "t"}

    def test_prose_without_braces_returns_none(self):
        from core.workflow.generator.llm_response import parse_stage_json as _parse_stage_json

        assert _parse_stage_json("好的，我来帮你规划这个工作流。") is None

    def test_blank_returns_none(self):
        from core.workflow.generator.llm_response import parse_stage_json as _parse_stage_json

        assert _parse_stage_json("   ") is None


class TestEmptyStreamFallsBackToBlocking:
    """A stream that yields nothing must be retried once without streaming."""

    def test_silent_stream_recovers_via_blocking_call(self):
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        builder = json.dumps({"config": {}})

        class _SilentStreamModel:
            def __init__(self) -> None:
                self.blocking_calls = 0

            def invoke_llm(self, *, prompt_messages, model_parameters, stream):
                is_planner = "workflow planner" in str(prompt_messages[0].content).lower()
                text = json.dumps(planner) if is_planner else builder
                if stream:
                    return iter(())
                self.blocking_calls += 1
                return _llm_result(text)

        model_instance = _SilentStreamModel()
        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert model_instance.blocking_calls >= 1
        assert not any(error["code"] == "INVALID_JSON" for error in result["errors"])


class TestModelMaxOutputTokens:
    """Reading the model's declared output ceiling must never break generation."""

    def test_reads_the_declared_max_tokens_rule(self):
        from core.workflow.generator.llm_response import model_max_output_tokens as _model_max_output_tokens

        model_instance = MagicMock()
        model_instance.get_model_schema.return_value.parameter_rules = [
            SimpleNamespace(name="temperature", max=2),
            SimpleNamespace(name="max_tokens", max=16384),
        ]

        assert _model_max_output_tokens(model_instance) == 16384

    def test_returns_none_when_the_rule_is_absent(self):
        from core.workflow.generator.llm_response import model_max_output_tokens as _model_max_output_tokens

        model_instance = MagicMock()
        model_instance.get_model_schema.return_value.parameter_rules = [
            SimpleNamespace(name="temperature", max=2),
        ]

        assert _model_max_output_tokens(model_instance) is None

    def test_returns_none_when_the_rule_declares_no_max(self):
        from core.workflow.generator.llm_response import model_max_output_tokens as _model_max_output_tokens

        model_instance = MagicMock()
        model_instance.get_model_schema.return_value.parameter_rules = [
            SimpleNamespace(name="max_tokens", max=None),
        ]

        assert _model_max_output_tokens(model_instance) is None

    def test_schema_lookup_failure_is_swallowed(self):
        from core.workflow.generator.llm_response import model_max_output_tokens as _model_max_output_tokens

        model_instance = MagicMock()
        model_instance.get_model_schema.side_effect = RuntimeError("plugin daemon unreachable")

        assert _model_max_output_tokens(model_instance) is None

    def test_model_without_the_method_is_tolerated(self):
        from core.workflow.generator.llm_response import model_max_output_tokens as _model_max_output_tokens

        class _BareModel:
            pass

        assert _model_max_output_tokens(_BareModel()) is None


class TestChunkFinishReason:
    """Providers spell the truncation reason differently; normalise before comparing."""

    def test_normalises_case_and_separators(self):
        assert chunk_finish_reason(_llm_chunk("", "MAX-TOKENS")) == "max_tokens"

    def test_missing_reason_is_empty(self):
        assert chunk_finish_reason(_llm_chunk("hi")) == ""


class TestOutputTruncation:
    """Hitting the model's output ceiling must fail loudly, never silently."""

    def test_planner_truncation_reports_output_truncated(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = lambda **kwargs: _truncated_stream('{"title": "x", "nodes": [')

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        codes = [error["code"] for error in result["errors"]]
        assert codes == ["OUTPUT_TRUNCATED"]
        assert "output truncated" in result["errors"][0]["detail"]

    def test_planner_truncation_receives_one_compact_retry(self):
        model_instance = MagicMock()
        model_instance.invoke_llm.side_effect = lambda **kwargs: _truncated_stream('{"nodes": [')

        WorkflowGenerator.generate_workflow_graph(
            model_instance=model_instance,
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert model_instance.invoke_llm.call_count == 2

    def test_builder_truncation_no_longer_passes_a_half_config(self):
        # Regression: json_repair turns a cut-off config into a valid dict, so
        # the old `isinstance(config, dict)` check waved a half-written node
        # straight into the graph.
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }

        class _TruncatingBuilderModel:
            def invoke_llm(self, *, prompt_messages, model_parameters, stream):
                if "workflow planner" in str(prompt_messages[0].content).lower():
                    return _stream_text(json.dumps(planner))
                return _truncated_stream('{"config": {"title": "Half writ')

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=_TruncatingBuilderModel(),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        codes = [error["code"] for error in result["errors"]]
        assert "OUTPUT_TRUNCATED" in codes
        assert any("Builder node" in error["detail"] for error in result["errors"])

    def test_normal_stop_reason_is_not_treated_as_truncation(self):
        planner = {
            "title": "x",
            "description": "x",
            "nodes": [
                {"id": "node1", "label": "Start", "node_type": "start", "purpose": "x"},
                {"id": "node2", "label": "End", "node_type": "end", "purpose": "x"},
            ],
            "edges": [{"source": "node1", "target": "node2"}],
        }
        builder = json.dumps({"config": {}})

        class _CleanStopModel:
            def invoke_llm(self, *, prompt_messages, model_parameters, stream):
                is_planner = "workflow planner" in str(prompt_messages[0].content).lower()
                return _truncated_stream(json.dumps(planner) if is_planner else builder, "stop")

        result = WorkflowGenerator.generate_workflow_graph(
            model_instance=_CleanStopModel(),
            model_parameters={},
            provider="openai",
            model_name="gpt-4o",
            model_mode="chat",
            mode="workflow",
            instruction="x",
        )

        assert not any(error["code"] == "OUTPUT_TRUNCATED" for error in result["errors"])


def test_stage_schema_error():
    err = StageSchemaError("planner", "missing key")
    assert str(err) == "planner schema invalid: missing key"
    assert err.stage == "planner"
