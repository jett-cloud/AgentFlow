from pathlib import Path

import pytest

from services.tool_plugin_generator import packager


def test_package_plugin_files_invokes_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(files_dir: str) -> bytes:
        plugin_dir = Path(files_dir)
        manifest = (plugin_dir / "manifest.yaml").read_text(encoding="utf-8")
        assert "version: 0.0.1" in manifest
        assert (plugin_dir / "tools" / "echo.py").read_text(encoding="utf-8") == "print('echo')\n"
        return b"PK_FAKE_DIFYPKG"

    monkeypatch.setattr(packager, "_run_plugin_package_cli", fake_run)

    result = packager.package_plugin_files(
        {
            "manifest.yaml": "version: 0.0.1\n",
            "tools/echo.py": "print('echo')\n",
        }
    )

    assert result == b"PK_FAKE_DIFYPKG"


def test_plugin_package_cli_fails_closed_when_binary_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DIFY_PLUGIN_CLI_PATH", raising=False)

    with pytest.raises(packager.PluginPackagingError, match="DIFY_PLUGIN_CLI_PATH"):
        packager._run_plugin_package_cli(str(tmp_path))


def test_package_plugin_files_strips_assets_prefix_from_icon_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(files_dir: str) -> bytes:
        manifest = (Path(files_dir) / "manifest.yaml").read_text(encoding="utf-8")
        provider = (Path(files_dir) / "provider" / "demo.yaml").read_text(encoding="utf-8")
        assert "icon: icon.svg" in manifest
        assert "_assets/icon.svg" not in manifest
        assert "icon: icon.svg" in provider
        return b"PK_FAKE_DIFYPKG"

    monkeypatch.setattr(packager, "_run_plugin_package_cli", fake_run)

    result = packager.package_plugin_files(
        {
            "manifest.yaml": "icon: _assets/icon.svg\n",
            "provider/demo.yaml": "identity:\n  icon: '_assets/icon.svg'\n",
        }
    )

    assert result == b"PK_FAKE_DIFYPKG"


def test_package_plugin_files_rewrites_legacy_dify_plugin_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(files_dir: str) -> bytes:
        requirements = (Path(files_dir) / "requirements.txt").read_text(encoding="utf-8")
        assert "dify-plugin>=0.9.0,<0.10.0" in requirements
        assert "dify-plugin>=0.0.1,<0.1.0" not in requirements
        assert "dify-plugin>=0.0.1\n" not in requirements
        return b"PK_FAKE_DIFYPKG"

    monkeypatch.setattr(packager, "_run_plugin_package_cli", fake_run)

    result = packager.package_plugin_files(
        {
            "requirements.txt": "dify-plugin>=0.0.1,<0.1.0\nhttpx>=0.28.0\n",
        }
    )

    assert result == b"PK_FAKE_DIFYPKG"


def test_package_plugin_files_rewrites_loose_dify_plugin_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(files_dir: str) -> bytes:
        requirements = (Path(files_dir) / "requirements.txt").read_text(encoding="utf-8")
        assert requirements.strip().splitlines()[0] == "dify-plugin>=0.9.0,<0.10.0"
        assert "httpx>=0.27.0" in requirements
        return b"PK_FAKE_DIFYPKG"

    monkeypatch.setattr(packager, "_run_plugin_package_cli", fake_run)

    result = packager.package_plugin_files(
        {
            "requirements.txt": "dify-plugin>=0.0.1\nhttpx>=0.27.0\n",
        }
    )

    assert result == b"PK_FAKE_DIFYPKG"


def test_normalize_requirements_pins_away_from_broken_010() -> None:
    assert packager._normalize_requirements("dify-plugin>=0.9.0,<1.0.0\n") == (
        "dify-plugin>=0.9.0,<0.10.0\n"
    )


def test_normalize_main_py_rewrites_bare_plugin_ctor() -> None:
    broken = "from dify_plugin import Plugin\n\nplugin = Plugin()\n\nif __name__ == '__main__':\n    plugin.run()\n"
    fixed = packager._normalize_main_py(broken)
    assert "Plugin(DifyPluginEnv())" in fixed
    assert "Plugin()" not in fixed.replace("Plugin(DifyPluginEnv())", "")


def test_package_plugin_files_rewrites_bare_main_py(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(files_dir: str) -> bytes:
        main_py = (Path(files_dir) / "main.py").read_text(encoding="utf-8")
        assert "Plugin(DifyPluginEnv())" in main_py
        assert packager._BARE_PLUGIN_CTOR_RE.search(main_py) is None
        return b"PK_FAKE_DIFYPKG"

    monkeypatch.setattr(packager, "_run_plugin_package_cli", fake_run)

    result = packager.package_plugin_files(
        {
            "main.py": "from dify_plugin import Plugin\n\nplugin = Plugin()\n",
        }
    )

    assert result == b"PK_FAKE_DIFYPKG"
