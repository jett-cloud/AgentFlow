"""Browser-facing labels for workflow-assist tools.

Tool names are stable protocol identifiers.  This module owns the concise
Chinese copy used by the progress timeline so browser clients never need to
render an internal method name.
"""

from __future__ import annotations

from typing import TypedDict


class ToolPresentation(TypedDict, total=False):
    visible: bool
    running: str
    success: str
    failure: str


TOOL_PRESENTATIONS: dict[str, ToolPresentation] = {
    "submit_workflow_plan": {"visible": False},
    "read_graph": {"visible": False},
    "read_node": {"visible": False},
    "activate_skills": {"visible": False},
    "inspect_node_schema": {"visible": False},
    "inspect_tool": {"visible": False},
    "ask_user": {"visible": False},
    "fail": {"visible": False},
    "build_node": {
        "visible": True,
        "running": "正在更新节点…",
        "success": "已更新节点",
        "failure": "更新节点失败",
    },
    "build_tool_node": {
        "visible": True,
        "running": "正在更新工具节点…",
        "success": "已更新工具节点",
        "failure": "更新工具节点失败",
    },
    "build_agent_node": {
        "visible": True,
        "running": "正在更新 Agent 节点…",
        "success": "已更新 Agent 节点",
        "failure": "更新 Agent 节点失败",
    },
    "build_loop": {
        "visible": True,
        "running": "正在更新循环…",
        "success": "已更新循环",
        "failure": "更新循环失败",
    },
    "build_iteration": {
        "visible": True,
        "running": "正在更新迭代…",
        "success": "已更新迭代",
        "failure": "更新迭代失败",
    },
    "delete_node": {
        "visible": True,
        "running": "正在删除节点…",
        "success": "已删除节点",
        "failure": "删除节点失败",
    },
    "connect": {
        "visible": True,
        "running": "正在连接节点…",
        "success": "已连接节点",
        "failure": "连接节点失败",
    },
    "disconnect": {
        "visible": True,
        "running": "正在断开节点连接…",
        "success": "已断开节点连接",
        "failure": "断开节点连接失败",
    },
    "validate_graph": {
        "visible": True,
        "running": "正在检查工作流结构…",
        "success": "工作流结构检查完成",
        "failure": "工作流结构检查失败",
    },
    "search_datasets": {
        "visible": True,
        "running": "正在查找知识库…",
        "success": "知识库查找完成",
        "failure": "知识库查找失败",
    },
    "search_tools": {
        "visible": True,
        "running": "正在查找工具…",
        "success": "工具查找完成",
        "failure": "工具查找失败",
    },
    "list_models": {
        "visible": True,
        "running": "正在查找可用模型…",
        "success": "模型查找完成",
        "failure": "模型查找失败",
    },
    "run_acceptance": {
        "visible": True,
        "running": "正在运行验收…",
        "success": "验收运行完成",
        "failure": "验收运行失败",
    },
    "inspect_attempt": {
        "visible": True,
        "running": "正在检查失败原因…",
        "success": "已检查失败原因",
        "failure": "检查失败原因失败",
    },
    "inspect_mock_targets": {
        "visible": True,
        "running": "正在检查模拟运行条件…",
        "success": "已检查模拟运行条件",
        "failure": "检查模拟运行条件失败",
    },
    "run_workflow": {
        "visible": True,
        "running": "正在试运行工作流场景…",
        "success": "工作流场景试运行完成",
        "failure": "工作流场景试运行失败",
    },
    "run_node": {
        "visible": True,
        "running": "正在验证可安全运行的节点…",
        "success": "节点运行验证完成",
        "failure": "节点运行验证失败",
    },
    "finish": {
        "visible": True,
        "running": "正在校验工作流…",
        "success": "工作流校验通过",
        "failure": "工作流校验失败",
    },
}


def tool_display(name: str, *, completed: bool, ok: bool = True) -> dict[str, object]:
    presentation = TOOL_PRESENTATIONS.get(name)
    if presentation is None:
        if not completed:
            return {"visible": True, "text": "正在处理…"}
        return {"visible": True, "text": "处理完成" if ok else "处理失败"}
    if presentation.get("visible") is False:
        return {"visible": False}
    state = "running" if not completed else ("success" if ok else "failure")
    return {"visible": True, "text": presentation[state]}
