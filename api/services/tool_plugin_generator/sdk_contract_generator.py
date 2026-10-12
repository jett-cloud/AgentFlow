"""Generate the static plugin-SDK contract from an installed SDK interpreter."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import inspect
import json
import sys
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "1"
DEFAULT_MODULES = (
    "dify_plugin",
    "dify_plugin.entities.tool",
    "dify_plugin.errors.tool",
)


def _public_exports(module_name: str) -> list[str]:
    module = importlib.import_module(module_name)
    declared = getattr(module, "__all__", None)
    if declared is not None:
        return sorted(str(name) for name in declared)
    exports = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        value = getattr(module, name)
        owner = getattr(value, "__module__", "")
        if isinstance(owner, str) and owner.startswith("dify_plugin"):
            exports.append(name)
    return sorted(exports)


def _method_contract(qualified_class: str) -> dict[str, Any]:
    module_name, class_name = qualified_class.rsplit(".", 1)
    cls = getattr(importlib.import_module(module_name), class_name)
    methods: dict[str, Any] = {}
    for name, member in inspect.getmembers(cls, predicate=callable):
        if name.startswith("_") or not name.startswith("create_"):
            continue
        signature = inspect.signature(member)
        required: list[str] = []
        optional: list[str] = []
        for parameter in signature.parameters.values():
            if parameter.name in {"self", "cls"}:
                continue
            if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
                continue
            target = required if parameter.default is parameter.empty else optional
            target.append(parameter.name)
        methods[name] = {"required": required, "optional": optional}
    return {"methods": methods}


def generate_contract(
    *,
    compatible_requirement: str,
    symbol_suggestions: dict[str, str] | None = None,
) -> dict[str, Any]:
    distribution = "dify-plugin"
    return {
        "distribution": distribution,
        "version": importlib.metadata.version(distribution),
        "compatible_requirement": compatible_requirement,
        "generator_version": GENERATOR_VERSION,
        "modules": {name: {"exports": _public_exports(name)} for name in DEFAULT_MODULES},
        "classes": {"dify_plugin.Tool": _method_contract("dify_plugin.Tool")},
        "symbol_suggestions": symbol_suggestions or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    parser.add_argument("--compatible-requirement", required=True)
    parser.add_argument("--base-contract", type=Path)
    args = parser.parse_args()
    suggestions: dict[str, str] = {}
    if args.base_contract:
        base = json.loads(args.base_contract.read_text(encoding="utf-8"))
        suggestions = dict(base.get("symbol_suggestions", {}))
    contract = generate_contract(
        compatible_requirement=args.compatible_requirement,
        symbol_suggestions=suggestions,
    )
    rendered = json.dumps(contract, indent=2, sort_keys=True) + "\n"
    if args.check:
        if args.check.read_text(encoding="utf-8") != rendered:
            sys.stderr.write(f"SDK contract drift detected: {args.check}\n")
            raise SystemExit(1)
        return
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
