"""Public facade for Workflow Assist chat and durable Agent runs.

Implementation lives in:

- ``chat_orchestration`` — SSE lifecycle, lease, supersede
- ``chat_persistence`` — RunEvent persistence and message.delta aggregation
- ``agent_initializer`` — restore, catalogues, ToolContext, model invoker

Existing callers and tests may keep importing from this module. Names that
tests patch on the implementation (catalogues, ``ToolContext``,
``iter_agent_events``, ``_commit_step``) are owned by the module that looks
them up at runtime, not by this facade.
"""

from core.db.session_factory import session_factory
from core.workflow.generator.agent.loop import iter_agent_events
from core.workflow.generator.agent.tools.tools import ToolContext
from services.workflow_assist.agent_initializer import (
    CHAT_SYSTEM_PROMPT,
    ChatRunLimits,
    DurableAgentRunContext,
    WorkflowAgentInvoker,
    WorkflowAssistRunInitializationError,
    _limits_from_config,
    _token_counter,
    chat_system_prompt,
    run_workflow_assist_agent,
)
from services.workflow_assist.chat_orchestration import (
    _ACTIVE_RUNS,
    ChatRunCancellation,
    abort_chat_run,
    iter_chat_events,
)
from services.workflow_assist.chat_persistence import (
    MESSAGE_DELTA_INTERVAL_SECONDS,
    MESSAGE_DELTA_MAX_BYTES,
    AgentEventPumpOutcome,
    MessageDeltaAggregator,
    _commit_step,
    _load_candidate_base_hash,
    persist_agent_events,
    persist_run_termination,
    persist_tail,
    persist_user_turn,
)
from services.workflow_assist.hydrate import hydrate_agent_bindings
from services.workflow_assist.knowledge_catalogue_loader import build_knowledge_catalogue
from services.workflow_assist.tool_catalogue_loader import build_tool_catalogue

__all__ = [
    "CHAT_SYSTEM_PROMPT",
    "MESSAGE_DELTA_INTERVAL_SECONDS",
    "MESSAGE_DELTA_MAX_BYTES",
    "_ACTIVE_RUNS",
    "AgentEventPumpOutcome",
    "ChatRunCancellation",
    "ChatRunLimits",
    "DurableAgentRunContext",
    "MessageDeltaAggregator",
    "ToolContext",
    "WorkflowAgentInvoker",
    "WorkflowAssistRunInitializationError",
    "_commit_step",
    "_limits_from_config",
    "_load_candidate_base_hash",
    "_token_counter",
    "abort_chat_run",
    "build_knowledge_catalogue",
    "build_tool_catalogue",
    "chat_system_prompt",
    "hydrate_agent_bindings",
    "iter_agent_events",
    "iter_chat_events",
    "persist_agent_events",
    "persist_run_termination",
    "persist_tail",
    "persist_user_turn",
    "run_workflow_assist_agent",
    "session_factory",
]
