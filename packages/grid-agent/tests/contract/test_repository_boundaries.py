from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[4]


def test_agent_has_no_scientific_simulator_dependencies() -> None:
    data = tomllib.loads((ROOT / "packages/grid-agent/pyproject.toml").read_text())
    dependencies = " ".join(data["project"]["dependencies"]).lower()
    for forbidden in ("pandapower", "numpy", "pandas", "scipy"):
        assert forbidden not in dependencies


def test_runtime_sources_have_no_research_checkout_reference() -> None:
    sentinel = "3th" + "-party/"
    roots = [ROOT / "packages", ROOT / "runtime", ROOT / "configs", ROOT / "knowledge"]
    checked = []
    for base in roots:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".toml", ".json", ".mjs", ".md"}:
                checked.append(path)
                assert sentinel not in path.read_text(encoding="utf-8")
    assert checked
