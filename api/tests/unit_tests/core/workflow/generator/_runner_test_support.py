"""Shared fakes and imports for workflow-generator responsibility tests."""

import json
import threading
import time
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast, override
from unittest.mock import MagicMock

import pytest
from jinja2 import Template

from configs import dify_config
from core.workflow.generator.compiler.node_builder import assemble_graph
from core.workflow.generator.graph.graph_postprocessor import GraphPostprocessor, postprocess_graph
from core.workflow.generator.model_io.llm_response import chunk_finish_reason
from core.workflow.generator.pipeline.planner_support import validate_planner_schema
from core.workflow.generator.pipeline.runner import WorkflowGenerator as _ProductionWorkflowGenerator
from core.workflow.generator.types import GraphDict
from core.workflow.generator.validation.graph_validator import GraphValidator, validate_graph
from core.workflow.generator.variables.variable_references import VariableReferences
from tests.unit_tests.core.workflow.generator.node_fixtures import node_config

__all__ = [
    "Any",
    "GraphDict",
    "GraphPostprocessor",
    "GraphValidator",
    "MagicMock",
    "SimpleNamespace",
    "Template",
    "VariableReferences",
    "WorkflowGenerator",
    "_GraphFixtureModel",
    "_ParallelBuilderModel",
    "_llm_chunk",
    "_llm_result",
    "_stream_builder_json",
    "_stream_planner_json",
    "_stream_text",
    "_truncated_stream",
    "assemble_graph",
    "cast",
    "chunk_finish_reason",
    "deepcopy",
    "dify_config",
    "json",
    "node_config",
    "postprocess_graph",
    "pytest",
    "threading",
    "time",
    "validate_graph",
    "validate_planner_schema",
]


def _llm_result(text: str) -> MagicMock:
    """Build a stand-in for ``LLMResult`` that the runner only reads as text."""
    result = MagicMock()
    result.message.get_text_content.return_value = text
    return result


def _llm_chunk(text: str, finish_reason: str | None = None):
    from graphon.model_runtime.entities.llm_entities import LLMResultChunk, LLMResultChunkDelta
    from graphon.model_runtime.entities.message_entities import AssistantPromptMessage

    return LLMResultChunk(
        model="gpt-4o",
        prompt_messages=[],
        delta=LLMResultChunkDelta(
            index=0,
            message=AssistantPromptMessage(content=text),
            finish_reason=finish_reason,
        ),
    )


def _stream_text(text: str):
    chunk_size = max(1, len(text) // 4)
    for index in range(0, len(text), chunk_size):
        yield _llm_chunk(text[index : index + chunk_size])


def _ensure_test_token_counter(model_instance: object) -> None:
    """Make legacy model fakes satisfy the production tokenizer protocol."""
    try:
        token_count = model_instance.get_llm_num_tokens([])  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        token_count = None
    if isinstance(token_count, int):
        return
    model_instance.get_llm_num_tokens = (  # type: ignore[attr-defined]
        lambda messages: sum(len(str(message.content or "")) for message in messages) // 4
    )


class WorkflowGenerator(_ProductionWorkflowGenerator):
    """Test facade that upgrades old fakes to the current model protocol."""

    @classmethod
    @override
    def _iter_generation_events(cls, *, model_instance: Any, **kwargs: Any):
        _ensure_test_token_counter(model_instance)
        yield from super()._iter_generation_events(model_instance=model_instance, **kwargs)


class _GraphFixtureModel:
    """Adapt full-graph fixtures to the production per-node model protocol."""

    def __init__(self, planner: str, graph: str) -> None:
        planner_payload = json.loads(planner)
        graph_payload = json.loads(graph)
        graph_nodes = [node for node in graph_payload.get("nodes", []) if isinstance(node, dict)]
        used_indexes: set[int] = set()
        graph_node_by_plan_id: dict[str, dict[str, Any]] = {}

        for plan_node in planner_payload.get("nodes", []):
            plan_type = plan_node.get("node_type")
            plan_label = plan_node.get("label")
            match_index = next(
                (
                    index
                    for index, graph_node in enumerate(graph_nodes)
                    if index not in used_indexes
                    and isinstance(graph_node.get("data"), dict)
                    and graph_node["data"].get("type") == plan_type
                    and graph_node["data"].get("title") == plan_label
                ),
                None,
            )
            if match_index is None:
                match_index = next(
                    (
                        index
                        for index, graph_node in enumerate(graph_nodes)
                        if index not in used_indexes
                        and isinstance(graph_node.get("data"), dict)
                        and graph_node["data"].get("type") == plan_type
                    ),
                    None,
                )
            if match_index is None:
                continue
            used_indexes.add(match_index)
            graph_node = graph_nodes[match_index]
            node_id = str(graph_node.get("id") or "")
            plan_node["id"] = node_id
            if graph_node.get("parentId"):
                plan_node["parent"] = str(graph_node["parentId"])
            graph_node_by_plan_id[node_id] = graph_node

        plan_ids = {str(node.get("id") or "") for node in planner_payload.get("nodes", [])}
        planner_payload["edges"] = [
            {key: edge[key] for key in ("source", "target", "sourceHandle", "targetHandle") if key in edge}
            for edge in graph_payload.get("edges", [])
            if isinstance(edge, dict) and edge.get("source") in plan_ids and edge.get("target") in plan_ids
        ]

        self._planner = planner_payload
        self._graph_node_by_plan_id = graph_node_by_plan_id
        self.invoke_llm = MagicMock(side_effect=self._invoke)

    def _invoke(self, *, prompt_messages, model_parameters, stream):
        system_prompt = str(prompt_messages[0].content)
        if "workflow planner" in system_prompt.lower():
            text = json.dumps(self._planner)
        else:
            prompt = "\n".join(str(message.content) for message in prompt_messages)
            node_id = next(node_id for node_id in self._graph_node_by_plan_id if f"id={node_id}, type=" in prompt)
            data = deepcopy(self._graph_node_by_plan_id[node_id].get("data") or {})
            had_prompt = "prompt_template" in data
            data = node_config(str(data.get("type")), data)
            if data.get("type") == "llm" and not had_prompt and "# Output language\n\nEnglish" in prompt:
                data["prompt_template"] = [{"role": "user", "text": "Process the input."}]
            for shared_key in ("type", "title", "desc", "selected"):
                data.pop(shared_key, None)
            text = json.dumps({"config": data})
        if stream:
            return _stream_text(text)
        return _llm_result(text)


class _ParallelBuilderModel:
    """Thread-safe fake that blocks the first ``barrier_parties`` node builders together."""

    def __init__(
        self,
        planner: dict[str, Any],
        configs: dict[str, dict[str, Any]],
        *,
        invalid_node_id: str | None = None,
        barrier_parties: int | None = None,
    ) -> None:
        self._planner = planner
        self._configs = configs
        self._invalid_node_id = invalid_node_id
        self._barrier_parties = barrier_parties if barrier_parties is not None else (2 if len(configs) >= 2 else 0)
        self._barrier = threading.Barrier(self._barrier_parties) if self._barrier_parties >= 2 else None
        self._lock = threading.Lock()
        self._builder_calls = 0
        self._calls_by_node: dict[str, int] = {}
        self._active_builders = 0
        self.max_active_builders = 0
        self.planner_calls = 0
        self.planner_prompt_messages: list[Any] = []
        self.builder_prompt_messages: dict[str, list[Any]] = {}

    @property
    def builder_calls(self) -> int:
        return self._builder_calls

    def calls_for(self, node_id: str) -> int:
        return self._calls_by_node.get(node_id, 0)

    def invoke_llm(self, *, prompt_messages, model_parameters, stream):
        system_prompt = str(prompt_messages[0].content)
        if "workflow planner" in system_prompt.lower():
            with self._lock:
                self.planner_calls += 1
                self.planner_prompt_messages = list(prompt_messages)
            text = json.dumps(self._planner)
        else:
            user_prompt = "\n".join(str(message.content) for message in prompt_messages)
            node_id = next(node_id for node_id in self._configs if f"id={node_id}" in user_prompt)
            with self._lock:
                call_index = self._builder_calls
                self._builder_calls += 1
                self._calls_by_node[node_id] = self._calls_by_node.get(node_id, 0) + 1
                self.builder_prompt_messages[node_id] = list(prompt_messages)
                self._active_builders += 1
                self.max_active_builders = max(self.max_active_builders, self._active_builders)
            try:
                if self._barrier is not None and call_index < self._barrier_parties:
                    self._barrier.wait(timeout=2)
                if node_id == self._invalid_node_id:
                    text = "not a json object"
                else:
                    text = json.dumps({"config": self._configs[node_id]})
            finally:
                with self._lock:
                    self._active_builders -= 1
        if stream:
            return _stream_text(text)
        return _llm_result(text)


def _stream_planner_json() -> str:
    return json.dumps(
        {
            "title": "URL Summarizer",
            "description": "Fetch a URL, summarize it, return the summary.",
            "app_name": "Summarizer",
            "icon": "🔗",
            "nodes": [
                {"label": "Start", "node_type": "start", "purpose": "User submits URL."},
                {"label": "Summarize", "node_type": "llm", "purpose": "Summarize the page."},
                {"label": "End", "node_type": "end", "purpose": "Return summary."},
            ],
        }
    )


def _stream_builder_json() -> str:
    return json.dumps(
        {
            "nodes": [
                {
                    "id": "node1",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {"type": "start", "title": "Start", "desc": "", "variables": []},
                },
                {
                    "id": "node2",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "llm",
                        "title": "Summarize",
                        "desc": "",
                        "prompt_template": [{"role": "user", "text": "{{#node1.url#}}"}],
                    },
                },
                {
                    "id": "node3",
                    "type": "custom",
                    "position": {"x": 0, "y": 0},
                    "data": {
                        "type": "end",
                        "title": "End",
                        "desc": "",
                        "outputs": [{"variable": "summary", "value_selector": ["node2", "text"]}],
                    },
                },
            ],
            "edges": [
                {"id": "x", "source": "node1", "target": "node2", "type": "custom"},
                {"id": "y", "source": "node2", "target": "node3", "type": "custom"},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 0.7},
        }
    )


def _truncated_stream(text: str, finish_reason: str = "length"):
    """Stream ``text`` and close with a provider-reported truncation."""
    yield _llm_chunk(text)
    yield _llm_chunk("", finish_reason)
