"""Single metadata registry for every public Workflow Assist node type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from core.workflow.generator.compiler.intents.agent_intent import AgentNodeBuildIntent
from core.workflow.generator.compiler.intents.container_intent import IterationBuildIntent, LoopBuildIntent
from core.workflow.generator.compiler.intents.node_intent import (
    AnswerStructureIntent,
    AssignerStructureIntent,
    CodeStructureIntent,
    DocumentExtractorStructureIntent,
    EndStructureIntent,
    HttpRequestStructureIntent,
    HumanInputStructureIntent,
    IfElseStructureIntent,
    KnowledgeRetrievalStructureIntent,
    ListOperatorStructureIntent,
    LLMStructureIntent,
    ParameterExtractorStructureIntent,
    QuestionClassifierStructureIntent,
    StartStructureIntent,
    TemplateStructureIntent,
    VariableAggregatorStructureIntent,
)
from core.workflow.generator.compiler.intents.tool_intent import ToolNodeBuildIntent

BuildToolName = Literal["build_node", "build_tool_node", "build_agent_node", "build_loop", "build_iteration"]
TypedIntentSurface = Literal["top_level", "container_child"]


@dataclass(frozen=True)
class NodeIntentSpec:
    build_tool: BuildToolName
    intent_model: type[BaseModel] | None
    typed_surfaces: tuple[TypedIntentSurface, ...] = ()


NODE_INTENT_SPECS: dict[str, NodeIntentSpec] = {
    "start": NodeIntentSpec("build_node", StartStructureIntent, ("top_level", "container_child")),
    "end": NodeIntentSpec("build_node", EndStructureIntent, ("top_level", "container_child")),
    "answer": NodeIntentSpec("build_node", AnswerStructureIntent, ("top_level", "container_child")),
    "llm": NodeIntentSpec("build_node", LLMStructureIntent, ("top_level", "container_child")),
    "knowledge-retrieval": NodeIntentSpec(
        "build_node", KnowledgeRetrievalStructureIntent, ("top_level", "container_child")
    ),
    "code": NodeIntentSpec("build_node", CodeStructureIntent, ("top_level", "container_child")),
    "template-transform": NodeIntentSpec("build_node", TemplateStructureIntent, ("top_level", "container_child")),
    "http-request": NodeIntentSpec("build_node", HttpRequestStructureIntent, ("top_level", "container_child")),
    "tool": NodeIntentSpec("build_tool_node", ToolNodeBuildIntent, ("top_level", "container_child")),
    "agent": NodeIntentSpec("build_agent_node", AgentNodeBuildIntent, ("top_level", "container_child")),
    "if-else": NodeIntentSpec("build_node", IfElseStructureIntent, ("top_level", "container_child")),
    "question-classifier": NodeIntentSpec(
        "build_node", QuestionClassifierStructureIntent, ("top_level", "container_child")
    ),
    "parameter-extractor": NodeIntentSpec(
        "build_node", ParameterExtractorStructureIntent, ("top_level", "container_child")
    ),
    "document-extractor": NodeIntentSpec(
        "build_node", DocumentExtractorStructureIntent, ("top_level", "container_child")
    ),
    "variable-aggregator": NodeIntentSpec(
        "build_node", VariableAggregatorStructureIntent, ("top_level", "container_child")
    ),
    "list-operator": NodeIntentSpec("build_node", ListOperatorStructureIntent, ("top_level", "container_child")),
    "assigner": NodeIntentSpec("build_node", AssignerStructureIntent, ("top_level", "container_child")),
    "human-input": NodeIntentSpec("build_node", HumanInputStructureIntent, ("top_level", "container_child")),
    "iteration": NodeIntentSpec("build_iteration", IterationBuildIntent, ("top_level",)),
    "loop": NodeIntentSpec("build_loop", LoopBuildIntent, ("top_level",)),
}


def node_intent_spec(node_type: str) -> NodeIntentSpec | None:
    return NODE_INTENT_SPECS.get(node_type)


__all__ = [
    "NODE_INTENT_SPECS",
    "BuildToolName",
    "NodeIntentSpec",
    "TypedIntentSurface",
    "node_intent_spec",
]
