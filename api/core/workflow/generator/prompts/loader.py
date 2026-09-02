"""Load Markdown prompt files shipped beside this package.

Paths are relative to ``core/workflow/generator/prompts/``. Missing or
out-of-tree files return empty content so callers can treat unknown node
types the same way ``get_node_config_snippet`` always has.
"""

from functools import cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parent
ALWAYS_ON_CHAR_LIMIT = 4000
PLAYBOOK_SKILLS = (
    "create-from-scratch",
    "repair-validation",
    "bind-resources",
    "edit-local-node",
)


def _safe_path(relative: str) -> Path | None:
    if not relative or relative.startswith(("/", "\\")):
        return None
    candidate = (_ROOT / relative).resolve()
    try:
        candidate.relative_to(_ROOT)
    except ValueError:
        return None
    return candidate


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    remainder = text[3:].lstrip("\n")
    marker = "\n---"
    end = remainder.find(marker)
    if end < 0:
        return {}, text
    loaded = yaml.safe_load(remainder[:end])
    meta = loaded if isinstance(loaded, dict) else {}
    body = remainder[end + len(marker) :].lstrip("\n")
    return meta, body


def _read_parts(relative: str) -> tuple[dict[str, Any], str]:
    path = _safe_path(relative)
    if path is None or not path.is_file():
        return {}, ""
    return _split_frontmatter(path.read_text(encoding="utf-8"))


@cache
def read_prompt(relative: str) -> str:
    """Return the Markdown body with YAML frontmatter stripped. Missing → ``""``."""
    _meta, body = _read_parts(relative)
    return body


@cache
def read_frontmatter(relative: str) -> dict[str, Any]:
    """Return parsed YAML frontmatter. Missing file or no fence → ``{}``."""
    meta, _body = _read_parts(relative)
    return meta


def playbook_index() -> list[tuple[str, str]]:
    """``(name, description)`` for the four always-on playbook catalogue lines."""
    entries: list[tuple[str, str]] = []
    for name in PLAYBOOK_SKILLS:
        meta = read_frontmatter(f"agent/skills/{name}/SKILL.md")
        description = str(meta.get("description") or "").strip()
        entries.append((name, description))
    return entries


def always_on_system_prompt() -> str:
    """Stable system prefix: hard rules plus playbook names, no skill bodies."""
    body = read_prompt("agent/SYSTEM.md").rstrip()
    lines = [body, "", "# Playbooks"]
    for name, description in playbook_index():
        suffix = f": {description}" if description else ""
        lines.append(f"- {name}{suffix}")
    return "\n".join(lines) + "\n"


@cache
def node_config_snippets() -> dict[str, str]:
    """Parse ``nodes.md`` H2 sections into ``{node_type: snippet}``."""
    snippets: dict[str, str] = {}
    current = ""
    buf: list[str] = []
    for line in read_prompt("nodes.md").splitlines():
        if line.startswith("## "):
            if current:
                snippets[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
            continue
        if current:
            buf.append(line)
    if current:
        snippets[current] = "\n".join(buf).strip()
    return snippets


def read_node_snippet(node_type: str) -> str:
    """Return one node-type section from ``nodes.md``. Unknown → ``""``."""
    if not node_type or any(token in node_type for token in ("/", "\\", "#")):
        return ""
    return node_config_snippets().get(node_type, "")
