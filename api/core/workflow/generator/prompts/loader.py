"""Load Markdown prompt files shipped beside this package.

Paths are relative to ``core/workflow/generator/prompts/``. Missing or
out-of-tree files return empty content so callers can treat unknown node
types the same way ``get_node_config_snippet`` always has.

Workflow-agent skills are discovered from a trusted directory only. Callers
look up skills by registered name; they never pass a filesystem path.
"""

from functools import cache
from operator import itemgetter
from pathlib import Path
from typing import Any, TypedDict

import yaml

_ROOT = Path(__file__).resolve().parent
_SKILLS_ROOT = _ROOT / "agent" / "skills"
ALWAYS_ON_CHAR_LIMIT = 10000


class SkillSummary(TypedDict):
    name: str
    description: str


class SkillRecord(TypedDict):
    name: str
    description: str
    body: str


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


def load_skill_records(root: Path) -> tuple[SkillRecord, ...]:
    """Discover ``SKILL.md`` files under ``root`` and validate each record.

    Raises ``ValueError`` on a missing fence, empty name/description/body,
    directory/name mismatch, or duplicate name. Output is sorted by name.
    """
    skill_root = root.resolve()
    if not skill_root.is_dir():
        raise ValueError(f"Skill directory does not exist: {skill_root}")
    files = sorted(path for path in skill_root.rglob("SKILL.md") if path.is_file())
    if not files:
        raise ValueError(f"No SKILL.md files found under {skill_root}")

    records: list[SkillRecord] = []
    seen: dict[str, Path] = {}
    for path in files:
        try:
            path.resolve().relative_to(skill_root)
        except ValueError as exc:
            raise ValueError(f"Skill file {path} is outside the trusted skill root {skill_root}") from exc
        directory_name = path.parent.name
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise ValueError(f"Skill {directory_name!r} is missing YAML frontmatter")
        meta, body = _split_frontmatter(text)
        name = str(meta.get("name") or "").strip()
        description = str(meta.get("description") or "").strip()
        body = body.strip()
        if not name:
            raise ValueError(f"Skill {directory_name!r} is missing a name")
        if name != directory_name:
            raise ValueError(f"Skill name {name!r} must equal directory name {directory_name!r}")
        if not description:
            raise ValueError(f"Skill {name!r} is missing a description")
        if not body:
            raise ValueError(f"Skill {name!r} is missing a body")
        previous = seen.get(name)
        if previous is not None:
            raise ValueError(f"Duplicate skill name {name!r} ({previous} and {path})")
        seen[name] = path
        records.append({"name": name, "description": description, "body": body})
    records.sort(key=itemgetter("name"))
    return tuple(records)


@cache
def _cached_skill_records() -> tuple[SkillRecord, ...]:
    return load_skill_records(_SKILLS_ROOT)


def skill_summaries() -> tuple[SkillSummary, ...]:
    """Return deterministic name/description summaries sorted by name."""
    return tuple(
        SkillSummary(name=record["name"], description=record["description"]) for record in _cached_skill_records()
    )


def registered_skill_names() -> tuple[str, ...]:
    """Return registered skill names in catalogue order."""
    return tuple(item["name"] for item in skill_summaries())


def skill_body(name: str) -> str | None:
    """Return one registered skill body; never resolve an arbitrary path."""
    if not isinstance(name, str) or not name:
        return None
    if any(token in name for token in ("/", "\\", "..")):
        return None
    for record in _cached_skill_records():
        if record["name"] == name:
            return record["body"]
    return None


def render_skill_catalogue() -> str:
    """Render compact name/description entries for the system prompt."""
    lines = ["# Available skills", ""]
    for item in skill_summaries():
        lines.append(f"- {item['name']}: {item['description']}")
    return "\n".join(lines) + "\n"


def available_node_types() -> tuple[str, ...]:
    """Return ``nodes.md`` H2 titles in file order."""
    return tuple(node_config_snippets().keys())


def render_available_node_types() -> str:
    """Render a compact node-type directory from ``nodes.md`` headings."""
    names = ", ".join(available_node_types())
    return f"# Available node types\n\n{names}\n"


def always_on_system_prompt() -> str:
    """Stable system prefix: hard rules, skill names, and node type names."""
    body = read_prompt("agent/SYSTEM.md").rstrip()
    skills = render_skill_catalogue().rstrip()
    nodes = render_available_node_types().rstrip()
    return f"{body}\n\n{skills}\n\n{nodes}\n"


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
