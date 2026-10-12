"""Load the versioned SDK surface used by generated tool plugins."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SdkContract:
    distribution: str
    version: str
    compatible_requirement: str
    generator_version: str
    modules: dict[str, frozenset[str]]
    classes: dict[str, dict[str, Any]]
    symbol_suggestions: dict[str, str]

    def exports(self, module: str) -> frozenset[str] | None:
        return self.modules.get(module)


@lru_cache(maxsize=1)
def load_sdk_contract() -> SdkContract:
    path = Path(__file__).with_name("resources") / "dify_plugin_sdk_0_9.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return SdkContract(
        distribution=str(document["distribution"]),
        version=str(document["version"]),
        compatible_requirement=str(document["compatible_requirement"]),
        generator_version=str(document.get("generator_version", "legacy")),
        modules={
            name: frozenset(str(symbol) for symbol in value["exports"])
            for name, value in document["modules"].items()
        },
        classes=dict(document.get("classes", {})),
        symbol_suggestions={str(key): str(value) for key, value in document.get("symbol_suggestions", {}).items()},
    )


def validate_configured_runtime_sdk() -> None:
    """Fail startup when deployment metadata and the generated contract drift."""
    runtime_version = os.environ.get("PLUGIN_DAEMON_SDK_VERSION", "").strip()
    if not runtime_version:
        return
    contract = load_sdk_contract()
    if runtime_version != contract.version:
        raise RuntimeError(
            f"Plugin daemon SDK {runtime_version} does not match generated contract {contract.version}"
        )
