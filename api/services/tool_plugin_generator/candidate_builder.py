"""Build one canonical, traceable source snapshot for plugin publication.

Every consumer in a publish attempt must use ``canonical_files`` from the same
result.  This prevents validation, preview mapping, packaging, and installation
from silently operating on different versions of the generated source.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from services.tool_plugin_generator.packager import normalize_plugin_source_files
from services.tool_plugin_generator.preflight import BuildDiagnostic, ToolPluginPreflightError, run_preflight
from services.tool_plugin_generator.preview_mapper import map_files_to_preview_tool


def _files_digest(files: Mapping[str, str]) -> str:
    payload = json.dumps(
        {str(path): str(content) for path, content in sorted(files.items())},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class CanonicalSourceSnapshot:
    draft_digest: str
    canonical_files: dict[str, str]
    canonical_digest: str


@dataclass(frozen=True)
class CandidateSource(CanonicalSourceSnapshot):
    preview: dict[str, Any] | None = None
    diagnostics: tuple[BuildDiagnostic, ...] = ()


def canonicalize_candidate_source(draft_files: Mapping[str, str]) -> CanonicalSourceSnapshot:
    draft = {str(path): str(content) for path, content in draft_files.items()}
    draft_digest = _files_digest(draft)
    canonical = normalize_plugin_source_files(draft)
    return CanonicalSourceSnapshot(
        draft_digest=draft_digest,
        canonical_files=canonical,
        canonical_digest=_files_digest(canonical),
    )


def prepare_canonical_candidate(
    snapshot: CanonicalSourceSnapshot,
    *,
    author: str | None = None,
    plugin_name: str | None = None,
    tool_name: str | None = None,
    resolve_dependencies: bool = False,
) -> CandidateSource:
    """Validate and preview an already canonicalized source snapshot."""
    report = run_preflight(
        snapshot.canonical_files,
        author=author,
        plugin_name=plugin_name,
        resolve_dependencies=resolve_dependencies,
    )
    if not report.ok:
        raise ToolPluginPreflightError(
            list(report.diagnostics),
            draft_digest=snapshot.draft_digest,
            canonical_digest=snapshot.canonical_digest,
        )

    preview = None
    if author is not None and plugin_name is not None:
        preview = map_files_to_preview_tool(
            snapshot.canonical_files,
            author=author,
            plugin_name=plugin_name,
            tool_name=tool_name,
        )

    return CandidateSource(
        draft_digest=snapshot.draft_digest,
        canonical_files=snapshot.canonical_files,
        canonical_digest=snapshot.canonical_digest,
        preview=preview,
        diagnostics=report.diagnostics,
    )


def prepare_candidate_source(
    draft_files: Mapping[str, str],
    *,
    author: str | None = None,
    plugin_name: str | None = None,
    tool_name: str | None = None,
    resolve_dependencies: bool = False,
) -> CandidateSource:
    """Canonicalize once, then validate and preview that exact snapshot."""
    snapshot = canonicalize_candidate_source(draft_files)
    return prepare_canonical_candidate(
        snapshot,
        author=author,
        plugin_name=plugin_name,
        tool_name=tool_name,
        resolve_dependencies=resolve_dependencies,
    )
