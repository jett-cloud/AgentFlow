from types import SimpleNamespace
from typing import Any, cast

from core.workflow.generator.agent.graph_ops import empty_graph
from core.workflow.generator.agent.loop import iter_agent_events
from core.workflow.generator.agent.tools import ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.agent.types import AgentMessage, AgentSession
from core.workflow.generator.llm_response import LLMJsonClient, ModelInvoker
from core.workflow.generator.node_builder import BuilderInput
from services.workflow_assist.chat import WorkflowAgentInvoker


class RecordingModel:
    """Records invoke_llm kwargs and returns a queued chunk iterator."""

    def __init__(self, chunks: list[object] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chunks = chunks if chunks is not None else [object(), object()]

    def invoke_llm(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        if kwargs.get("stream") is not True:
            raise AssertionError("native loop must call invoke_llm with stream=True")
        return iter(self.chunks)


def _invoker(*, native_tools: bool, model: RecordingModel) -> WorkflowAgentInvoker:
    return WorkflowAgentInvoker(
        model_instance=model,  # type: ignore[arg-type]
        model_parameters={"temperature": 0},
        json_client=SimpleNamespace(),  # type: ignore[arg-type]
        tools=[],
        native_tools=native_tools,
    )


def _stream_chunk(*, text: str = "") -> SimpleNamespace:
    message = SimpleNamespace(content=text, tool_calls=[])
    return SimpleNamespace(delta=SimpleNamespace(message=message, finish_reason=None))


def _tool_context() -> ToolContext:
    return ToolContext(
        env=ToolEnv(
            tenant_id="tenant-1",
            mode="workflow",
            tool_entries=[],
            knowledge_entries=[],
            installed_tools=None,
            installed_dataset_ids=None,
            knowledge_available=False,
            tools_available=False,
            builder_input=BuilderInput(
                provider="openai",
                model_name="gpt-4o",
                model_mode="chat",
                mode="workflow",
                instruction="生成中文摘要工作流",
                ideal_output="",
                plan_nodes=[],
                plan_edges=[],
                tool_catalogue_text="",
                knowledge_catalogue_text="",
                start_inputs=[],
                current_graph=None,
                output_language="zh-Hans",
            ),
            llm_client=LLMJsonClient(model_instance=cast("ModelInvoker", object()), model_parameters={}),
            hydrate_graph=None,
        ),
        state=ToolTurnState(graph=empty_graph()),
    )


def test_native_tools_invoke_llm_with_stream_true() -> None:
    model = RecordingModel()
    invoker = _invoker(native_tools=True, model=model)
    chunks = invoker.iter_chunks([])
    assert chunks is not None
    assert list(chunks) == model.chunks
    assert model.calls
    assert model.calls[0]["stream"] is True


def test_json_path_iter_chunks_is_none() -> None:
    model = RecordingModel()
    invoker = _invoker(native_tools=False, model=model)
    assert invoker.iter_chunks([]) is None
    assert model.calls == []


def test_native_iter_agent_events_consumes_iter_chunks_not_invoke() -> None:
    model = RecordingModel(chunks=[_stream_chunk(text="正在"), _stream_chunk(text="创建")])
    invoker = _invoker(native_tools=True, model=model)

    def invoke_must_not_run(messages: list[object]) -> object:
        raise AssertionError("iter_agent_events must consume iter_chunks, not invoke")

    invoker.invoke = invoke_must_not_run  # type: ignore[method-assign]
    context = _tool_context()
    session = AgentSession(
        messages=[
            AgentMessage(
                sequence=1,
                event_type="message",
                role="user",
                status="completed",
                payload={"text": "做 RAG 测试工作流"},
            )
        ],
        candidate_graph=context.state.graph,
        candidate_revision=context.state.candidate_revision,
        candidate_base_hash=None,
        compacted_until_sequence=None,
        compacted_state=None,
        generation_mode="workflow",
        last_validation=None,
    )
    events = list(
        iter_agent_events(
            session=session,
            context=context,
            invoker=invoker,
            cancellation=SimpleNamespace(reason=lambda: None),
            limits=SimpleNamespace(
                max_model_calls=8,
                max_tool_calls=None,
                max_total_tokens=None,
                max_elapsed_time=None,
            ),
        )
    )
    names = [name for name, _ in events]
    assert names[:2] == ["message.delta", "message.delta"]
    assert "message" not in names
    assert model.calls
    assert all(call["stream"] is True for call in model.calls)
