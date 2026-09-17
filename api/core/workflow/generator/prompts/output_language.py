"""Detect and localize workflow-generator user-visible output.

One-shot generation detects its instruction language. Conversations inherit the
first user instruction's language unless the user explicitly switches it.
Model thought deltas remain untouched.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

OutputLanguage = Literal["en", "zh-Hans"]

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+")
_PLACEHOLDER_RE = re.compile(r"\{\{#.*?#\}\}")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def detect_output_language(instruction: str) -> OutputLanguage:
    """Return the dominant supported language in one user instruction."""
    chinese_count = len(_CJK_RE.findall(instruction))
    latin_count = sum(len(word) for word in _LATIN_WORD_RE.findall(instruction))
    return "zh-Hans" if chinese_count * 2 >= latin_count else "en"


def resolve_output_language(instructions: Iterable[str]) -> OutputLanguage:
    """Replay user text in order; configuration answers cannot change language.

    Only a leading language directive switches an established conversation.
    This avoids interpreting model identifiers or quoted node content as locale.
    """
    language: OutputLanguage | None = None
    for instruction in instructions:
        text = instruction.strip()
        if not text:
            continue
        directive = re.match(
            r"^(?:请\s*)?(?:(?:改用|切换到|使用|用)\s*(中文|英文|英语)|"
            r"(?:please\s+)?(?:respond|reply|answer|continue)\s+in\s+(Chinese|English)|"
            r"(?:please\s+)?(?:switch\s+to|use)\s+(Chinese|English))",
            text,
            re.IGNORECASE,
        )
        if directive:
            target = next(value for value in directive.groups() if value).lower()
            language = "zh-Hans" if target in {"中文", "chinese"} else "en"
        elif language is None:
            language = detect_output_language(text)
    return language or "zh-Hans"


def output_language_name(language: OutputLanguage) -> str:
    return "Simplified Chinese (简体中文)" if language == "zh-Hans" else "English"


def text_matches_output_language(text: str, language: OutputLanguage) -> bool:
    """Return whether natural-language text matches the requested output language.

    Dify placeholders and URLs are technical values rather than prose, so they
    do not affect the language decision. Text without either CJK or Latin words
    is neutral and therefore valid for either supported language.
    """
    normalized = _URL_RE.sub("", _PLACEHOLDER_RE.sub("", text))
    chinese_count = len(_CJK_RE.findall(normalized))
    latin_count = sum(len(word) for word in _LATIN_WORD_RE.findall(normalized))
    if not chinese_count and not latin_count:
        return True
    if language == "zh-Hans":
        return chinese_count * 2 >= latin_count
    return latin_count > chinese_count * 2


def localized_generator_message(
    key: str,
    language: OutputLanguage,
    *,
    count: int = 0,
    label: str = "",
) -> str:
    """Render deterministic SSE copy without changing event payload structure."""
    messages = {
        "en": {
            "planning": "Planning workflow",
            "building": "Building nodes",
            "plan_ready": f"Planned {count} nodes",
            "node_start": f"Generating node {label}",
            "node_done": f"Node {label} completed",
        },
        "zh-Hans": {
            "planning": "正在规划工作流",
            "building": "正在生成节点",
            "plan_ready": f"已规划 {count} 个节点",
            "node_start": f"正在生成节点 {label}",
            "node_done": f"节点 {label} 已完成",
        },
    }
    return messages[language].get(key, key)
