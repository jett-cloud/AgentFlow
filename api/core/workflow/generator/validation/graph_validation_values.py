"""graph validation values."""

from core.workflow.generator.types import (
    WorkflowGenerateErrorDict,
)
from graphon.enums import BuiltinNodeTypes


def _err(code: str, detail: str, node_id: str = "") -> WorkflowGenerateErrorDict:
    out: WorkflowGenerateErrorDict = {"code": code, "detail": detail}
    if node_id:
        out["node_id"] = node_id
    return out


_CONTAINER_TYPES = frozenset({BuiltinNodeTypes.ITERATION, BuiltinNodeTypes.LOOP})


_ID_FIELDS = frozenset({"start_node_id", "iteration_id", "loop_id", "parentId"})
