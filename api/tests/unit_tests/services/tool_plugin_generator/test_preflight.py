from services.tool_plugin_generator.preflight import run_preflight


def _valid_files() -> dict[str, str]:
    return {
        "manifest.yaml": "version: 0.0.1\nauthor: acme\nname: demo\n",
        "main.py": "pass\n",
        "requirements.txt": "dify-plugin>=0.9.0,<0.10.0\n",
        "README.md": "# Demo\n",
        "tools/echo.yaml": "identity:\n  name: echo\nparameters: []\n",
        "tools/echo.py": "pass\n",
    }


def test_preflight_aggregates_manifest_reference_and_sdk_symbol_errors() -> None:
    files = _valid_files()
    files["manifest.yaml"] += "privacy: PRIVACY.md\n"
    files["tools/echo.py"] = (
        "from dify_plugin.errors.tool import ToolInvokeError\n"
        "raise ToolInvokeError('failed')\n"
    )

    report = run_preflight(files, author="acme", plugin_name="demo")

    assert report.ok is False
    assert {item.code for item in report.errors} >= {
        "MISSING_REFERENCED_FILE",
        "SDK_SYMBOL_NOT_FOUND",
    }
    sdk_error = next(item for item in report.errors if item.code == "SDK_SYMBOL_NOT_FOUND")
    assert sdk_error.path == "tools/echo.py"
    assert sdk_error.line == 1
    assert sdk_error.suggestion


def test_preflight_reports_duplicate_requirements_without_failing() -> None:
    files = _valid_files()
    files["requirements.txt"] += "dify_plugin>=0.9.0,<0.10.0\n"

    report = run_preflight(files)

    assert report.ok is True
    assert any(item.code == "DUPLICATE_REQUIREMENT" for item in report.diagnostics)


def test_preflight_reports_incompatible_exact_versions() -> None:
    files = _valid_files()
    files["requirements.txt"] = "httpx==0.27.0\nhttpx==0.28.0\n"

    report = run_preflight(files)

    assert report.ok is False
    assert any(item.code == "UNSATISFIABLE_REQUIREMENTS" for item in report.errors)


def test_preflight_accepts_exported_sdk_import() -> None:
    files = _valid_files()
    files["tools/echo.py"] = (
        "from dify_plugin.errors.tool import ToolProviderCredentialValidationError\n"
    )

    report = run_preflight(files, author="acme", plugin_name="demo")

    assert all(item.code != "SDK_SYMBOL_NOT_FOUND" for item in report.diagnostics)


def test_preflight_reports_any_unknown_symbol_from_known_sdk_module() -> None:
    files = _valid_files()
    files["tools/echo.py"] = "from dify_plugin.entities.tool import ImaginaryMessage\n"

    report = run_preflight(files, author="acme", plugin_name="demo")

    diagnostic = next(item for item in report.diagnostics if item.code == "SDK_SYMBOL_NOT_FOUND")
    assert diagnostic.details == {
        "module": "dify_plugin.entities.tool",
        "symbol": "ImaginaryMessage",
        "sdk_version": "0.9.1",
        "sdk_requirement": ">=0.9.0,<0.10.0",
    }


def test_preflight_reports_sdk_method_signature_mismatch() -> None:
    files = _valid_files()
    files["tools/echo.py"] = "result = self.create_image_message(blob=b'image')\n"

    report = run_preflight(files, author="acme", plugin_name="demo")

    diagnostic = next(item for item in report.diagnostics if item.code == "SDK_CALL_SIGNATURE_MISMATCH")
    assert diagnostic.line == 1
    assert "unexpected keyword(s): blob" in diagnostic.message
    assert "missing required argument(s): image_url" in diagnostic.message


def test_preflight_accepts_valid_sdk_method_call() -> None:
    files = _valid_files()
    files["tools/echo.py"] = "result = self.create_blob_message(blob=b'image')\n"

    report = run_preflight(files, author="acme", plugin_name="demo")

    assert all(item.code != "SDK_CALL_SIGNATURE_MISMATCH" for item in report.diagnostics)


def test_preflight_reports_manifest_provider_and_entrypoint_references() -> None:
    files = _valid_files()
    files["manifest.yaml"] += (
        "type: plugin\n"
        "plugins:\n  tools:\n    - provider/missing.yaml\n"
        "meta:\n  runner:\n    language: python\n    entrypoint: missing_main\n"
    )

    report = run_preflight(files, author="acme", plugin_name="demo")

    missing = [item for item in report.errors if item.code == "MISSING_REFERENCED_FILE"]
    assert {item.details["referenced_path"] for item in missing if item.details} == {
        "provider/missing.yaml",
        "missing_main.py",
    }


def test_preflight_reports_invalid_manifest_type() -> None:
    files = _valid_files()
    files["manifest.yaml"] += "type: model\n"

    report = run_preflight(files, author="acme", plugin_name="demo")

    assert any(item.code == "INVALID_MANIFEST_TYPE" for item in report.errors)


def test_preflight_rejects_direct_url_requirement_without_resolving() -> None:
    files = _valid_files()
    files["requirements.txt"] = "demo @ https://example.com/demo.whl\n"

    report = run_preflight(files)

    assert any(item.code == "UNSAFE_REQUIREMENT_SOURCE" for item in report.errors)


def test_preflight_reports_uv_resolution_failure(monkeypatch) -> None:
    files = _valid_files()
    monkeypatch.setattr(
        "services.tool_plugin_generator.preflight.resolve_requirements",
        lambda _content: __import__(
            "services.tool_plugin_generator.dependency_resolver", fromlist=["DependencyResolution"]
        ).DependencyResolution(ok=False, message="No solution found"),
    )

    report = run_preflight(files, resolve_dependencies=True)

    diagnostic = next(item for item in report.errors if item.code == "UV_RESOLUTION_FAILED")
    assert diagnostic.details == {
        "resolver_output": "No solution found",
        "error_type": None,
        "elapsed_ms": 0,
        "cache_hit": False,
    }


def test_preflight_aggregates_versioned_schema_errors_across_documents() -> None:
    files = _valid_files()
    files["provider/demo.yaml"] = (
        "identity:\n  name: ''\n"
        "credentials_for_provider:\n  api_key:\n    type: ''\n"
    )
    files["tools/echo.yaml"] = (
        "identity:\n  name: echo\n"
        "parameters:\n"
        "  - name: prompt\n    type: string\n"
        "  - name: prompt\n    type: string\n    form: llm\n"
    )

    report = run_preflight(files, author="acme", plugin_name="demo")

    schema_errors = [item for item in report.errors if item.code == "YAML_SCHEMA_VIOLATION"]
    assert {item.path for item in schema_errors} == {"provider/demo.yaml", "tools/echo.yaml"}
    assert {item.details["schema_version"] for item in schema_errors if item.details} == {
        "tool-plugin-v1"
    }
    assert len(schema_errors) >= 3


def test_preflight_reports_bidirectional_provider_tool_source_and_icon_errors() -> None:
    files = _valid_files()
    files["provider/demo.yaml"] = (
        "identity:\n  name: demo\n  icon: missing.svg\n"
        "tools:\n  - tools/missing.yaml\n"
        "extra:\n  python:\n    source: provider/missing.py\n"
    )

    report = run_preflight(files, author="acme", plugin_name="demo")

    missing_paths = {
        item.details["referenced_path"]
        for item in report.errors
        if item.code == "MISSING_REFERENCED_FILE" and item.details
    }
    assert missing_paths >= {
        "_assets/missing.svg",
        "provider/missing.py",
        "tools/missing.yaml",
    }
    assert any(
        item.code == "UNREFERENCED_TOOL" and item.path == "tools/echo.yaml"
        for item in report.errors
    )


def test_preflight_schema_checks_i18n_enums_resource_and_runner() -> None:
    files = _valid_files()
    files["manifest.yaml"] = (
        "version: 0.0.1\nauthor: acme\nname: demo\ntype: plugin\n"
        "label:\n  zh_Hans: 演示\n"
        "resource:\n  memory: 0\n"
        "meta:\n  version: 0.0.1\n  arch: [riscv]\n"
        "  runner:\n    language: node\n    version: '20'\n    entrypoint: main\n"
    )
    files["tools/echo.yaml"] = (
        "identity:\n  name: echo\n"
        "parameters:\n  - name: prompt\n    type: imaginary\n    form: api\n"
    )

    report = run_preflight(files, author="acme", plugin_name="demo")

    locations = {
        item.details["location"]
        for item in report.errors
        if item.code == "YAML_SCHEMA_VIOLATION" and item.details
    }
    assert locations >= {
        "label",
        "resource.memory",
        "meta.arch.0",
        "meta.runner.language",
        "parameters.0.type",
        "parameters.0.form",
    }


def test_preflight_checks_source_class_count_and_unique_provider_ownership() -> None:
    files = _valid_files()
    files["tools/echo.yaml"] += "extra:\n  python:\n    source: tools/echo.py\n"
    files["provider/one.yaml"] = "identity:\n  name: one\ntools: [tools/echo.yaml]\n"
    files["provider/two.yaml"] = "identity:\n  name: two\ntools: [tools/echo.yaml]\n"

    report = run_preflight(files, author="acme", plugin_name="demo")

    class_error = next(item for item in report.errors if item.code == "INVALID_SOURCE_CLASS_COUNT")
    assert class_error.path == "tools/echo.py"
    assert class_error.details == {"expected_base": "Tool", "count": 0}
    duplicate = next(
        item for item in report.errors if item.code == "DUPLICATE_TOOL_PROVIDER_REFERENCE"
    )
    assert duplicate.details == {"providers": ["provider/one.yaml", "provider/two.yaml"]}


def test_preflight_rejects_runtime_sdk_contract_version_drift(monkeypatch) -> None:
    monkeypatch.setenv("PLUGIN_DAEMON_SDK_VERSION", "0.9.2")

    report = run_preflight(_valid_files(), author="acme", plugin_name="demo")

    diagnostic = next(
        item for item in report.errors if item.code == "SDK_CONTRACT_VERSION_MISMATCH"
    )
    assert diagnostic.details == {
        "runtime_version": "0.9.2",
        "contract_version": "0.9.1",
        "generator_version": "1",
    }
