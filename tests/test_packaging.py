from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_editable_install_limits_setuptools_discovery_to_app_package():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    package_finder = data["tool"]["setuptools"]["packages"]["find"]

    assert package_finder["include"] == ["app", "app.*"]
    assert package_finder["exclude"] == ["runtime*", "searxng*", "cookie_manager*"]
