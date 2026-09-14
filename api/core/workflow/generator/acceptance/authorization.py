"""Server-issued, graph-bound requests for one live acceptance execution."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.workflow.generator.acceptance.evidence import canonical_graph_hash
from core.workflow.generator.graph.types import MinimalGraphDict
from core.workflow.generator.types import GraphDict

LIVE_CONSENT_QUESTION_ID = "live_run_consent"


class LiveAcceptanceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    title: str
    node_type: str
    capabilities: list[str]
    may_have_side_effects: bool


class LiveAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    graph_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_revision: int = Field(ge=0)
    nodes: list[LiveAcceptanceNode]
    max_executions: Literal[1] = 1
    max_steps: Literal[32] = 32
    max_seconds: Literal[60] = 60


def build_live_acceptance_request(graph: MinimalGraphDict | GraphDict, *, revision: int) -> LiveAcceptanceRequest:
    nodes: list[LiveAcceptanceNode] = []
    for node in graph.get("nodes", []):
        data = node.get("data") or {}
        kind = str(data.get("type") or "")
        if kind not in {"llm", "agent", "tool", "knowledge-retrieval", "http-request"}:
            continue
        capabilities: list[str] = []
        model = data.get("model")
        if isinstance(model, dict):
            capabilities.append(f"{model.get('provider', '')}/{model.get('name', '')}")
        if kind == "tool":
            capabilities.append(f"{data.get('provider_id', '')}/{data.get('tool_name', '')}")
        for key in ("dify_tools", "mcp_tools"):
            for binding in data.get(key) or []:
                if isinstance(binding, dict):
                    capabilities.append(
                        str(binding.get("tool_name") or binding.get("name") or binding.get("id") or key)
                    )
        nodes.append(
            LiveAcceptanceNode(
                node_id=node["id"],
                title=str(data.get("title") or node["id"]),
                node_type=kind,
                capabilities=capabilities,
                may_have_side_effects=kind in {"tool", "http-request", "agent"},
            )
        )
    return LiveAcceptanceRequest(
        request_id=uuid4().hex,
        graph_hash=canonical_graph_hash(graph),
        candidate_revision=revision,
        nodes=nodes,
    )
