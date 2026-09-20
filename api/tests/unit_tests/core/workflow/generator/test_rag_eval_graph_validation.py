"""Regression: RAG eval graph the assist agent once marked valid."""

from core.workflow.generator.types import GraphDict, WorkflowGenerateErrorCode
from core.workflow.generator.validation.graph_validator import validate_graph


def _rag_eval_graph(*, code_output_type: str = "array") -> GraphDict:
    """Shape of the 读库出题 + 逐题评测 candidate after connect, before repair."""
    return {
        "nodes": [
            {
                "id": "node_start",
                "data": {
                    "type": "start",
                    "variables": [
                        {"variable": "eval_count", "label": "Eval Count", "type": "number"},
                        {"variable": "source_query", "label": "Source Query", "type": "paragraph"},
                    ],
                },
            },
            {
                "id": "node_source_retrieval",
                "data": {
                    "type": "knowledge-retrieval",
                    "retrieval_mode": "multiple",
                    "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
                    "query_variable_selector": ["node_start", "source_query"],
                    "dataset_ids": ["982a2097-2807-4142-840f-63fc6cf5e73b"],
                },
            },
            {
                "id": "node_agent_gen",
                "data": {
                    "type": "llm",
                    "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
                    "context": {"enabled": False, "variable_selector": []},
                    "prompt_template": [{"role": "user", "text": "{{#node_source_retrieval.result#}}"}],
                },
            },
            {
                "id": "node_parse",
                "data": {
                    "type": "code",
                    "title": "解析评测问题集",
                    "variables": [{"variable": "text", "value_selector": ["node_agent_gen", "text"]}],
                    "outputs": {"questions": {"type": code_output_type, "children": None}},
                    "code": "def main(text):\n    return {'questions': []}\n",
                    "code_language": "python3",
                },
            },
            {
                "id": "node_iter",
                "data": {
                    "type": "iteration",
                    "title": "逐题检索与判定",
                    "start_node_id": "node_iterstart",
                    "iterator_selector": ["node_parse", "questions"],
                    "output_selector": ["node_assemble", "result"],
                },
            },
            {
                "id": "node_iterstart",
                "type": "custom-iteration-start",
                "parentId": "node_iter",
                "data": {"type": "iteration-start", "isInIteration": True},
            },
            {
                "id": "node_retrieval",
                "parentId": "node_iter",
                "data": {
                    "type": "knowledge-retrieval",
                    "title": "逐题检索知识库",
                    "retrieval_mode": "multiple",
                    "multiple_retrieval_config": {"top_k": 3, "reranking_enable": False},
                    "query_variable_selector": ["node_iter", "item", "question"],
                    "dataset_ids": ["982a2097-2807-4142-840f-63fc6cf5e73b"],
                },
            },
            {
                "id": "node_prepare",
                "parentId": "node_iter",
                "data": {
                    "type": "code",
                    "title": "准备判定上下文",
                    "variables": [{"variable": "q", "value_selector": ["node_iter", "item", "question"]}],
                    "outputs": {"context": {"type": "string", "children": None}},
                    "code": "def main(q):\n    return {'context': q}\n",
                    "code_language": "python3",
                },
            },
            {
                "id": "node_assemble",
                "parentId": "node_iter",
                "data": {
                    "type": "code",
                    "title": "组装单题结果",
                    "variables": [{"variable": "q", "value_selector": ["node_iter", "item", "question"]}],
                    "outputs": {"result": {"type": "object", "children": None}},
                    "code": "def main(q):\n    return {'result': q}\n",
                    "code_language": "python3",
                },
            },
            {
                "id": "node_code",
                "data": {
                    "type": "code",
                    "title": "统计检索准确率",
                    "variables": [{"variable": "rows", "value_selector": ["node_iter", "output"]}],
                    "outputs": {
                        "accuracy": {"type": code_output_type, "children": None},
                        "hit_count": {"type": "number", "children": None},
                    },
                    "code": "def main(rows):\n    return {'accuracy': 0, 'hit_count': 0}\n",
                    "code_language": "python3",
                },
            },
            {
                "id": "node_end",
                "data": {
                    "type": "end",
                    "title": "输出评测报告",
                    "outputs": [
                        {"variable": "accuracy", "value_selector": ["node_code", "accuracy"]},
                        {"variable": "hit_count", "value_selector": ["node_code", "hit_count"]},
                    ],
                },
            },
        ],
        "edges": [
            {"source": "node_start", "target": "node_source_retrieval"},
            {"source": "node_source_retrieval", "target": "node_agent_gen"},
            {"source": "node_agent_gen", "target": "node_parse"},
            {"source": "node_parse", "target": "node_iter"},
            {"source": "node_iter", "target": "node_code"},
            {"source": "node_code", "target": "node_end"},
            {"source": "node_iterstart", "target": "node_retrieval"},
            {"source": "node_retrieval", "target": "node_prepare"},
            {"source": "node_prepare", "target": "node_assemble"},
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.7},
    }


def test_rag_eval_graph_flags_illegal_code_types_and_missing_end_types() -> None:
    errors = validate_graph(graph=_rag_eval_graph(), mode="workflow")
    codes = {(error["code"], error.get("node_id")) for error in errors}

    assert (WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT, "node_parse") in codes
    assert (WorkflowGenerateErrorCode.INVALID_CODE_OUTPUT, "node_code") in codes
    assert (WorkflowGenerateErrorCode.INVALID_END_OUTPUT, "node_end") in codes
    assert any(error["code"] == WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE for error in errors)


def test_rag_eval_graph_is_structurally_valid_once_output_types_are_legal() -> None:
    graph = _rag_eval_graph(code_output_type="array[object]")
    graph["nodes"][3]["data"]["outputs"]["questions"]["children"] = {
        "question": {"type": "string", "children": None}
    }
    graph["nodes"][-2]["data"]["outputs"]["accuracy"] = {"type": "number", "children": None}
    for item in graph["nodes"][-1]["data"]["outputs"]:
        item["value_type"] = "number"

    errors = validate_graph(graph=graph, mode="workflow")

    assert errors == []


def test_iteration_rejects_nested_item_field_without_output_schema() -> None:
    graph = _rag_eval_graph(code_output_type="array[object]")
    graph["nodes"][-2]["data"]["outputs"]["accuracy"] = {"type": "number", "children": None}
    for item in graph["nodes"][-1]["data"]["outputs"]:
        item["value_type"] = "number"

    errors = validate_graph(graph=graph, mode="workflow")

    assert any(
        error["code"] == WorkflowGenerateErrorCode.UNRESOLVED_REFERENCE
        and error.get("node_id") == "node_iter"
        for error in errors
    )
