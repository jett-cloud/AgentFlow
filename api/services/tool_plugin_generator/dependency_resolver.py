"""Bounded, cached uv resolution without installing, building, or importing plugins."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

ResolutionErrorType = Literal[
    "conflict", "package_not_found", "network", "timeout", "no_distribution", "invalid_input", "process_error"
]


@dataclass(frozen=True)
class DependencyResolution:
    ok: bool
    message: str = ""
    skipped: bool = False
    error_type: ResolutionErrorType | None = None
    elapsed_ms: int = 0
    cache_hit: bool = False


_CACHE: OrderedDict[str, tuple[float, DependencyResolution]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_SEMAPHORE_LOCK = threading.Lock()
_SEMAPHORE: threading.BoundedSemaphore | None = None
_SEMAPHORE_SIZE: int | None = None


def _limit(name: str, default: int) -> int:
    return max(1, int(os.environ.get(name, str(default))))


def _resolver_semaphore() -> threading.BoundedSemaphore:
    global _SEMAPHORE, _SEMAPHORE_SIZE
    size = _limit("TOOL_PLUGIN_UV_PREFLIGHT_CONCURRENCY", 2)
    with _SEMAPHORE_LOCK:
        if _SEMAPHORE is None or size != _SEMAPHORE_SIZE:
            _SEMAPHORE = threading.BoundedSemaphore(size)
            _SEMAPHORE_SIZE = size
        return _SEMAPHORE


def _cache_key(content: str, *, index_url: str) -> str:
    payload = "\0".join((content, "3.12", "x86_64-unknown-linux-gnu", index_url))
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_cached(key: str) -> DependencyResolution | None:
    now = time.monotonic()
    ttl = float(os.environ.get("TOOL_PLUGIN_UV_PREFLIGHT_CACHE_TTL", "600"))
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        created_at, result = entry
        if now - created_at > ttl:
            del _CACHE[key]
            return None
        _CACHE.move_to_end(key)
        return replace(result, cache_hit=True)


def _put_cached(key: str, result: DependencyResolution) -> None:
    if not result.ok and result.error_type not in {
        "conflict", "package_not_found", "no_distribution", "invalid_input"
    }:
        return
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _limit("TOOL_PLUGIN_UV_PREFLIGHT_CACHE_SIZE", 256):
            _CACHE.popitem(last=False)


def _classify_failure(message: str) -> ResolutionErrorType:
    lowered = message.lower()
    if any(marker in lowered for marker in ("timed out", "timeout")):
        return "timeout"
    if any(marker in lowered for marker in ("connection", "network", "dns", "temporary failure", "tls")):
        return "network"
    if any(marker in lowered for marker in ("no solution found", "unsatisfiable", "incompatible")):
        return "conflict"
    if any(marker in lowered for marker in ("not found in the package registry", "could not find a version")):
        return "package_not_found"
    if any(marker in lowered for marker in ("no wheels", "no binary", "no matching distribution")):
        return "no_distribution"
    return "process_error"


def clear_resolution_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def resolve_requirements(content: str) -> DependencyResolution:
    started = time.monotonic()
    if os.environ.get("TOOL_PLUGIN_UV_PREFLIGHT_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return DependencyResolution(ok=True, skipped=True, message="uv preflight is disabled")
    if len(content.encode()) > _limit("TOOL_PLUGIN_UV_PREFLIGHT_MAX_BYTES", 65536):
        return DependencyResolution(ok=False, message="requirements.txt exceeds size limit", error_type="invalid_input")
    if len(content.splitlines()) > _limit("TOOL_PLUGIN_UV_PREFLIGHT_MAX_LINES", 500):
        return DependencyResolution(ok=False, message="requirements.txt exceeds line limit", error_type="invalid_input")

    uv_path = shutil.which("uv")
    if not uv_path:
        return DependencyResolution(ok=True, skipped=True, message="uv executable is unavailable")

    index_url = os.environ.get("PIP_MIRROR_URL", "").strip()
    key = _cache_key(content, index_url=index_url)
    cached = _get_cached(key)
    if cached is not None:
        return cached

    timeout = float(os.environ.get("TOOL_PLUGIN_UV_PREFLIGHT_TIMEOUT", "45"))
    with _resolver_semaphore(), tempfile.TemporaryDirectory(prefix="tool-plugin-uv-") as temp_dir:
        requirement_path = Path(temp_dir) / "requirements.in"
        requirement_path.write_text(content, encoding="utf-8")
        command = [
            uv_path, "pip", "compile", "--quiet", "--no-header", "--no-annotate", "--no-build",
            "--python-version", "3.12", "--python-platform", "x86_64-unknown-linux-gnu",
        ]
        if index_url:
            command.extend(["--index-url", index_url])
        command.append(str(requirement_path))
        try:
            process = subprocess.run(
                command, cwd=temp_dir, capture_output=True, check=False, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return DependencyResolution(
                ok=False,
                message=f"uv dependency resolution timed out after {timeout:g}s",
                error_type="timeout",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except OSError as exc:
            return DependencyResolution(
                ok=False,
                message=f"failed to start uv: {exc}",
                error_type="process_error",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    detail = (process.stderr or process.stdout or "uv dependency resolution failed").strip()[-4000:]
    result = DependencyResolution(
        ok=process.returncode == 0,
        message="" if process.returncode == 0 else detail,
        error_type=None if process.returncode == 0 else _classify_failure(detail),
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    _put_cached(key, result)
    return result
