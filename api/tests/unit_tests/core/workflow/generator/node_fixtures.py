"""Minimal runtime-valid defaults for tests about orchestration, not missing fields."""

import re
from copy import deepcopy


def node_config(node_type: str, overrides: dict | None = None) -> dict:
    defaults = {
        "llm": {
            "model": {"provider": "openai", "name": "gpt-4o", "mode": "chat", "completion_params": {}},
            "prompt_template": [{"role": "user", "text": "处理输入。"}],
            "context": {"enabled": False, "variable_selector": []},
        },
        "code": {"variables": [], "code_language": "python3", "code": "def main():\n    return {}"},
        "knowledge-retrieval": {"retrieval_mode": "multiple"},
        "iteration": {
            "start_node_id": "iterationstart",
            "iterator_selector": ["start", "items"],
            "output_selector": ["child", "result"],
        },
        "loop": {
            "start_node_id": "loopstart",
            "loop_count": 1,
            "break_conditions": [],
            "logical_operator": "and",
            "loop_variables": [],
        },
        "end": {
            "outputs": [
                {
                    "variable": "files",
                    "value_selector": ["sys", "files"],
                    "value_type": "array[file]",
                }
            ]
        },
    }
    return {**deepcopy(defaults.get(node_type, {})), **deepcopy(overrides or {})}


def builder_config(messages, overrides: dict | None = None) -> dict:
    match = re.search(r"id=[^,]+, type=([^,]+),", "\n".join(str(m.content) for m in messages))
    assert match is not None
    return node_config(match[1], overrides)
