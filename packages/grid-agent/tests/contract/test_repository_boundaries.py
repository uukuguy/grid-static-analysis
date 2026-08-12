import os
import re
import subprocess
import tomllib
from pathlib import Path

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


def test_operator_docs_use_current_state_paths() -> None:
    docs = {
        "README.md": (ROOT / "README.md").read_text(encoding="utf-8"),
        "docs/RUNBOOK.md": (ROOT / "docs/RUNBOOK.md").read_text(encoding="utf-8"),
    }
    combined = "\n".join(docs.values())

    for path, text in docs.items():
        assert "var/runs" not in text, path
        assert "var/pi/agent" not in text, path
        assert "var/runtime" not in text, path

    assert "runs/<question_id>/" in combined
    assert ".grid-agent/auth/pi" in combined
    assert ".grid-agent/runtime/pi" in combined


def test_tracked_operational_files_do_not_construct_legacy_active_state_paths() -> None:
    source_roots = (
        "packages/",
        "configs/",
        "knowledge/",
        "README.md",
        "docs/RUNBOOK.md",
        "docs/TASK.md",
        "Makefile",
        ".env.example",
    )
    completed = subprocess.run(
        ["git", "ls-files", *source_roots],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    tracked_files = [
        ROOT / line
        for line in completed.stdout.splitlines()
        if line
        and Path(line) != Path("packages/grid-agent/tests/contract/test_repository_boundaries.py")
        and (ROOT / line).suffix in TEXT_SUFFIXES
    ]
    legacy_var = "v" + "ar"
    forbidden_patterns = (
        re.compile(rf"['\"]{legacy_var}/(?:pi|runs)(?:/|['\"])"),
        re.compile(rf"['\"]{legacy_var}['\"]\s*/\s*['\"](?:pi|runs|runtime)['\"]"),
    )

    offenders: list[str] = []
    for path in tracked_files:
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))
                break

    assert offenders == []
    assert tracked_files
