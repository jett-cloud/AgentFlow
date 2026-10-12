from __future__ import annotations

import subprocess
from unittest.mock import Mock

import pytest

from services.tool_plugin_generator import dependency_resolver


@pytest.fixture(autouse=True)
def _clear_cache():
    dependency_resolver.clear_resolution_cache()


def test_resolver_uses_uv_without_building_or_installing(monkeypatch) -> None:
    monkeypatch.delenv("TOOL_PLUGIN_UV_PREFLIGHT_ENABLED", raising=False)
    monkeypatch.setattr(dependency_resolver.shutil, "which", Mock(return_value="/usr/local/bin/uv"))
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="httpx==0.28.1\n", stderr=""))
    monkeypatch.setattr(dependency_resolver.subprocess, "run", run)

    result = dependency_resolver.resolve_requirements("httpx>=0.28\n")

    assert result.ok is True
    command = run.call_args.args[0]
    assert command[:3] == ["/usr/local/bin/uv", "pip", "compile"]
    assert "--no-build" in command
    assert "install" not in command


def test_resolver_returns_bounded_failure_output(monkeypatch) -> None:
    monkeypatch.delenv("TOOL_PLUGIN_UV_PREFLIGHT_ENABLED", raising=False)
    monkeypatch.setattr(dependency_resolver.shutil, "which", Mock(return_value="uv"))
    monkeypatch.setattr(
        dependency_resolver.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="x" * 5000)),
    )

    result = dependency_resolver.resolve_requirements("missing-package==1\n")

    assert result.ok is False
    assert len(result.message) == 4000


@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        ("No solution found when resolving dependencies", "conflict"),
        ("package was not found in the package registry", "package_not_found"),
        ("TLS connection failed", "network"),
        ("No matching distribution", "no_distribution"),
    ],
)
def test_resolver_classifies_failures(monkeypatch, message: str, error_type: str) -> None:
    monkeypatch.setattr(dependency_resolver.shutil, "which", Mock(return_value="uv"))
    monkeypatch.setattr(
        dependency_resolver.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, stdout="", stderr=message)),
    )

    result = dependency_resolver.resolve_requirements("demo==1\n")

    assert result.error_type == error_type


def test_resolver_caches_deterministic_results(monkeypatch) -> None:
    monkeypatch.setattr(dependency_resolver.shutil, "which", Mock(return_value="uv"))
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="demo==1\n", stderr=""))
    monkeypatch.setattr(dependency_resolver.subprocess, "run", run)

    first = dependency_resolver.resolve_requirements("demo==1\n")
    second = dependency_resolver.resolve_requirements("demo==1\n")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert run.call_count == 1


def test_resolver_enforces_limits_and_controlled_mirror(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_PLUGIN_UV_PREFLIGHT_MAX_LINES", "1")
    too_large = dependency_resolver.resolve_requirements("one==1\ntwo==2\n")
    assert too_large.error_type == "invalid_input"

    monkeypatch.setenv("TOOL_PLUGIN_UV_PREFLIGHT_MAX_LINES", "10")
    monkeypatch.setenv("PIP_MIRROR_URL", "https://mirror.example/simple")
    monkeypatch.setattr(dependency_resolver.shutil, "which", Mock(return_value="uv"))
    run = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    monkeypatch.setattr(dependency_resolver.subprocess, "run", run)
    dependency_resolver.resolve_requirements("one==1\n")
    assert run.call_args.args[0][-3:-1] == ["--index-url", "https://mirror.example/simple"]


def test_resolver_reports_timeout_and_does_not_cache_transient_network_errors(monkeypatch) -> None:
    monkeypatch.setattr(dependency_resolver.shutil, "which", Mock(return_value="uv"))
    run = Mock(side_effect=subprocess.TimeoutExpired(["uv"], 1))
    monkeypatch.setattr(dependency_resolver.subprocess, "run", run)
    timed_out = dependency_resolver.resolve_requirements("demo==1\n")
    assert timed_out.error_type == "timeout"

    run.side_effect = None
    run.return_value = subprocess.CompletedProcess([], 1, stdout="", stderr="TLS connection failed")
    first = dependency_resolver.resolve_requirements("network-demo==1\n")
    second = dependency_resolver.resolve_requirements("network-demo==1\n")
    assert first.error_type == second.error_type == "network"
    assert run.call_count == 3
