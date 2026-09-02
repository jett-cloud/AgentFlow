from dataclasses import replace
from typing import cast

import pytest

from core.workflow.generator.agent.graph_ops import empty_graph
from core.workflow.generator.agent.tools import ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.llm_response import LLMJsonClient, ModelInvoker
from core.workflow.generator.node_builder import BuilderInput


def _builder_input() -> BuilderInput:
    return BuilderInput(
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
    )


def set_env(context: ToolContext, **changes: object) -> None:
    """Replace frozen ``ToolEnv`` fields on a test context."""
    context.env = replace(context.env, **changes)


@pytest.fixture
def tool_context() -> ToolContext:
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
            builder_input=_builder_input(),
            llm_client=LLMJsonClient(model_instance=cast("ModelInvoker", object()), model_parameters={}),
            hydrate_graph=None,
        ),
        state=ToolTurnState(graph=empty_graph()),
    )
