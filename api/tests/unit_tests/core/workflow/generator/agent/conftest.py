from dataclasses import replace
from typing import cast

import pytest

from core.workflow.generator.agent.tools.tools import ToolContext, ToolEnv, ToolTurnState
from core.workflow.generator.graph.graph_ops import empty_graph
from core.workflow.generator.model_io.llm_response import LLMJsonClient, ModelInvoker


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
            llm_client=LLMJsonClient(model_instance=cast("ModelInvoker", object()), model_parameters={}),
            agent_model_entries=(
                {"provider": "openai", "name": "gpt-4o", "model_type": "llm", "features": ()},
                {"provider": "openai", "name": "gpt-4.1", "model_type": "llm", "features": ()},
            ),
            models_available=True,
            output_language="zh-Hans",
            hydrate_graph=None,
        ),
        state=ToolTurnState(graph=empty_graph()),
    )
