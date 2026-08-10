import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[4]
TEXT_SUFFIXES = {".py", ".toml", ".json", ".mjs", ".md"}
PRUNED_DIR_NAMES = {".venv", "node_modules", ".pytest_cache", "__pycache__"}


def iter_first_party_files() -> list[Path]:
    checked = []
    roots = [ROOT / "packages", ROOT / "runtime", ROOT / "configs", ROOT / "knowledge"]
    for base in roots:
        if not base.exists():
            continue
        for current_root, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if name not in PRUNED_DIR_NAMES]
            root_path = Path(current_root)
            for filename in filenames:
                path = root_path / filename
                if path.suffix in TEXT_SUFFIXES:
                    checked.append(path)
    return checked


def test_agent_has_no_scientific_simulator_dependencies() -> None:
    data = tomllib.loads((ROOT / "packages/grid-agent/pyproject.toml").read_text())
    dependencies = " ".join(data["project"]["dependencies"]).lower()
    for forbidden in ("pandapower", "numpy", "pandas", "scipy"):
        assert forbidden not in dependencies


def test_first_party_scan_prunes_generated_directories() -> None:
    checked = iter_first_party_files()
    assert checked
    for path in checked:
        assert not PRUNED_DIR_NAMES.intersection(path.parts)


def test_runtime_sources_have_no_research_checkout_reference() -> None:
    sentinel = "3th" + "-party/"
    checked = iter_first_party_files()
    for path in checked:
        assert sentinel not in path.read_text(encoding="utf-8")
    assert checked
