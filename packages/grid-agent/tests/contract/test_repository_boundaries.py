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
    historical_plan = Path(
        "docs/superpowers/plans/2026-08-10-grid-static-analysis-walking-skeleton.md"
    )
    wp_a_foundation_plan = Path(
        "docs/superpowers/plans/2026-08-12-wp-a-semantic-foundation-validation.md"
    )
    approved_redesign = Path(
        "docs/superpowers/specs/2026-08-12-pandapower-semantic-capability-redesign.md"
    )
    superseded_marker = (
        "SUPERSEDED: Historical archive only; non-operative path details."
    )
    excluded_historical_plans = {historical_plan}
    checked_paths = (
        "packages/",
        "configs/",
        "knowledge/",
        "README.md",
        "docs/RUNBOOK.md",
        "docs/TASK.md",
        str(approved_redesign),
        "docs/superpowers/plans/",
        "Makefile",
        ".env.example",
    )
    completed = subprocess.run(
        ["git", "ls-files", *checked_paths],
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
        and (ROOT / line).exists()
        and (ROOT / line).suffix in TEXT_SUFFIXES
    ]
    legacy_var = "v" + "ar"
    forbidden_patterns = (
        re.compile(rf"\b{legacy_var}/(?:pi|runs|runtime)(?:/|\b)"),
        re.compile(rf"['\"]{legacy_var}['\"]\s*/\s*['\"](?:pi|runs|runtime)['\"]"),
    )

    offenders: list[str] = []
    for path in tracked_files:
        relative_path = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        if relative_path in excluded_historical_plans:
            assert superseded_marker in text, relative_path
            continue
        for pattern in forbidden_patterns:
            if pattern.search(text):
                offenders.append(str(relative_path))
                break

    assert offenders == []
    checked_relative_paths = {path.relative_to(ROOT) for path in tracked_files}
    assert approved_redesign in checked_relative_paths
    assert historical_plan in checked_relative_paths
    assert wp_a_foundation_plan in checked_relative_paths
    assert superseded_marker not in (
        ROOT / wp_a_foundation_plan
    ).read_text(encoding="utf-8")
    assert "### 17.2 WP-A: semantic foundation and validation baseline" in (
        ROOT / approved_redesign
    ).read_text(encoding="utf-8")
    assert tracked_files


def test_legacy_runtime_paths_are_absent() -> None:
    forbidden = [
        ROOT / "configs/prompts/grid-agent-system.md",
        ROOT / "packages/pi-grid-tools/src/hardened-bash.mjs",
        ROOT / "runtime/pi-runtime.lock.json",
        ROOT / "knowledge/index.json",
    ]

    assert [str(path) for path in forbidden if path.exists()] == []

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "packages").rglob("*.*")
        if path.suffix in {".py", ".mjs", ".json"}
        and not any(part in {"node_modules", ".venv", "__pycache__"} for part in path.parts)
    )
    legacy_request_class = "class " + "SimulatorRequest"
    legacy_operation_access = "request" + "." + "operation"
    legacy_query = "grid" + "_query"
    assert legacy_request_class not in source
    assert legacy_operation_access not in source
    assert legacy_query not in source


def test_current_sources_do_not_use_obsolete_provider_capture_path() -> None:
    checked_paths = (
        "packages/grid-agent/src/",
        "packages/pi-grid-tools/src/",
        "schemas/",
        "docs/architecture/",
    )
    completed = subprocess.run(
        ["git", "ls-files", *checked_paths],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    tracked_paths = [line for line in completed.stdout.splitlines() if line]
    checked_relative_paths = set(tracked_paths)
    assert {
        "packages/grid-agent/src/grid_agent/trajectory/static/assets/app.css",
        "packages/grid-agent/src/grid_agent/trajectory/static/assets/app.js",
        "packages/grid-agent/src/grid_agent/trajectory/static/index.html",
    }.issubset(checked_relative_paths)
    forbidden_terms = (
        "before_provider_request",
        "provider_payload",
        "HIDDEN_REASONING_KEYS",
        "CREDENTIAL_KEY_PATTERN",
        "drain_provider_requests",
    )

    grep = subprocess.run(
        [
            "git",
            "grep",
            "-I",
            "-n",
            *[option for term in forbidden_terms for option in ("-e", term)],
            "--",
            *checked_paths,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert grep.returncode == 1, grep.stdout or grep.stderr
    assert tracked_paths
