from types import SimpleNamespace

import pytest

from services.tool_plugin_generator import sdk_contract_generator
from services.tool_plugin_generator.sdk_contract import load_sdk_contract, validate_configured_runtime_sdk


def test_load_sdk_contract_exposes_runtime_sdk_surface() -> None:
    contract = load_sdk_contract()

    assert contract.version == "0.9.1"
    assert contract.generator_version == "1"
    exports = contract.exports("dify_plugin.errors.tool")
    assert exports is not None
    assert "ToolProviderCredentialValidationError" in exports
    assert "ToolInvokeError" not in exports
    assert contract.exports("unknown.module") is None


def test_contract_generator_reads_exports_version_and_method_signatures(monkeypatch) -> None:
    class Tool:
        __module__ = "dify_plugin"

        def create_text_message(self, text, meta=None):
            del text, meta

    modules = {
        "dify_plugin": SimpleNamespace(__all__=["Tool"], Tool=Tool),
        "dify_plugin.entities.tool": SimpleNamespace(ToolIdentity=type("ToolIdentity", (), {})),
        "dify_plugin.errors.tool": SimpleNamespace(
            ToolProviderCredentialValidationError=type(
                "ToolProviderCredentialValidationError",
                (),
                {"__module__": "dify_plugin.errors.tool"},
            )
        ),
    }
    modules["dify_plugin.entities.tool"].ToolIdentity.__module__ = "dify_plugin.entities.tool"
    monkeypatch.setattr(sdk_contract_generator.importlib, "import_module", modules.__getitem__)
    monkeypatch.setattr(sdk_contract_generator.importlib.metadata, "version", lambda _name: "0.9.1")

    contract = sdk_contract_generator.generate_contract(
        compatible_requirement=">=0.9.0,<0.10.0",
        symbol_suggestions={"old.Symbol": "Use new.Symbol"},
    )

    assert contract["generator_version"] == "1"
    assert contract["modules"]["dify_plugin"]["exports"] == ["Tool"]
    assert contract["classes"]["dify_plugin.Tool"]["methods"]["create_text_message"] == {
        "required": ["text"],
        "optional": ["meta"],
    }
    assert contract["symbol_suggestions"] == {"old.Symbol": "Use new.Symbol"}


def test_configured_runtime_sdk_version_must_match_contract(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_DAEMON_SDK_VERSION", "0.9.2")

    with pytest.raises(RuntimeError, match="does not match generated contract 0.9.1"):
        validate_configured_runtime_sdk()
