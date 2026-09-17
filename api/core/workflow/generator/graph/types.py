"""Minimal candidate graph types shared by compilation, validation, and the Agent."""

from typing import Any, NotRequired, TypedDict

from core.workflow.generator.types import GraphViewportDict


class MinimalGraphNodeDict(TypedDict):
    """One node of the graph as the agent builds it.

    ``MinimalGraphNodeDict``, ``MinimalGraphEdgeDict``, and ``MinimalGraphDict``
    describe the graph *before* ``graph_postprocessor.postprocess_graph`` runs.
    The postprocessor is the single normaliser that fills in the ReactFlow node
    ``type`` and ``position`` and the edge ``id`` and ``type``, all of which
    ``GraphDict`` in ``core.workflow.generator.types`` declares as required.
    These types exist so the agent's own surface stays honestly typed instead of
    casting an incomplete node to ``GraphNodeDict`` — a cast that would let the
    type checker bless a ``node["position"]`` that raises ``KeyError`` at run
    time. The one legitimate conversion to ``GraphDict`` belongs at the single
    boundary that hands the finished graph to the postprocessor.
    """

    id: str
    data: dict[str, Any]
    parentId: NotRequired[str]


class MinimalGraphEdgeDict(TypedDict):
    """One edge of the graph as the agent builds it. See ``MinimalGraphNodeDict``."""

    source: str
    target: str
    sourceHandle: NotRequired[str]


class MinimalGraphDict(TypedDict):
    """The agent's in-progress graph. See ``MinimalGraphNodeDict``."""

    nodes: list[MinimalGraphNodeDict]
    edges: list[MinimalGraphEdgeDict]
    viewport: GraphViewportDict
