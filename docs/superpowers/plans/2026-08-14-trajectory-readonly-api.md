# Read-only Trajectory API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve native and imported trajectory projections through a loopback-only, cursor-paginated, read-only API with allowlisted artifact retrieval.

**Architecture:** `TrajectoryRunCatalog` discovers runs through validated manifests and delegates replay/projection to `ProjectionService`. `ProjectionPager` enforces both record and byte budgets using HMAC-bound sequence cursors. FastAPI exposes only fixed GET routes; `ArtifactGateway` resolves refs through the verified ArtifactIndex and rejects every direct or escaping path.

**Tech Stack:** Python 3.12+, FastAPI 0.139, uvicorn 0.51, Pydantic 2.12, Typer 0.20, standard-library HMAC/secrets/pathlib, HTTPX/TestClient, pytest 9.

## Global Constraints

- The service binds to `127.0.0.1` by default and accepts only loopback hosts in the first release.
- API routes are GET/HEAD only; POST, PUT, PATCH, DELETE, WebSocket, and tool invocation routes do not exist.
- Run IDs come from discovered validated manifests, never request-to-path concatenation.
- Artifact refs resolve only through `ArtifactIndex`; arbitrary run files and raw Pi sidecars are not downloadable.
- Absolute paths, traversal, percent-encoded separators, escaping symlinks, device files, and unregistered files are rejected.
- Each projection page contains at most 500 records and at most 2 MiB of canonical JSON before transport encoding.
- Cursors bind analysis ID, view, source fingerprint, projection version, direction, and source sequence with HMAC-SHA256.
- Invalid, tampered, stale, foreign-run, and wrong-view cursors return distinct typed 400/409 errors.
- Responses use fixed content types, CSP, nosniff, frame-deny, no-referrer, and no-store headers.
- Markdown/raw artifact text is delivered as data with fixed media type; the API never renders executable HTML.
- The existing answer-producing CLI stdout contract is unchanged; `trajectory serve` is an operator service command and logs diagnostics to stderr.
- Use red/green TDD, focused tests first, and one atomic commit per task.

## File Map

### New production files

- `packages/grid-agent/src/grid_agent/trajectory/api/__init__.py`
- `packages/grid-agent/src/grid_agent/trajectory/api/models.py` — API response and typed error models.
- `packages/grid-agent/src/grid_agent/trajectory/api/catalog.py` — safe run discovery and summaries.
- `packages/grid-agent/src/grid_agent/trajectory/api/cursor.py` — HMAC cursor codec and stale checks.
- `packages/grid-agent/src/grid_agent/trajectory/api/paging.py` — record/byte-bounded sequence pages.
- `packages/grid-agent/src/grid_agent/trajectory/api/artifacts.py` — allowlisted artifact gateway.
- `packages/grid-agent/src/grid_agent/trajectory/api/app.py` — FastAPI routes and security middleware.
- `packages/grid-agent/src/grid_agent/trajectory/api/server.py` — uvicorn configuration and loopback guard.

### Modified production files

- `packages/grid-agent/pyproject.toml` and `packages/grid-agent/uv.lock` — FastAPI/uvicorn runtime, HTTPX dev dependency.
- `packages/grid-agent/src/grid_agent/application/paths.py` — `trajectory_cache_dir`.
- `packages/grid-agent/src/grid_agent/cli/app.py` — `trajectory serve` Typer subcommand.
- `Makefile` — `trajectory` convenience target and API tests.
- `docs/RUNBOOK.md` and `docs/MANUAL-VALIDATION.md` — local server operation/security checks.

### Tests

- `packages/grid-agent/tests/trajectory/api/test_catalog.py`
- `packages/grid-agent/tests/trajectory/api/test_cursor.py`
- `packages/grid-agent/tests/trajectory/api/test_paging.py`
- `packages/grid-agent/tests/trajectory/api/test_artifacts.py`
- `packages/grid-agent/tests/trajectory/api/test_app.py`
- `packages/grid-agent/tests/trajectory/api/test_server.py`
- `packages/grid-agent/tests/cli/test_app.py`

---

### Task 1: Dependencies and safe run catalog

**Files:**
- Modify: `packages/grid-agent/pyproject.toml`
- Modify: `packages/grid-agent/uv.lock`
- Modify: `packages/grid-agent/src/grid_agent/application/paths.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/__init__.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/models.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/catalog.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_catalog.py`

**Interfaces:**
- Adds runtime dependencies `fastapi>=0.139,<1` and `uvicorn>=0.51,<1`; adds dev `httpx>=0.28,<1`.
- Adds `ProjectPaths.trajectory_cache_dir -> .grid-agent/trajectory-cache`.
- Produces: `TrajectoryRunCatalog(runs_root, cache_root, projection_service).list_runs() -> tuple[RunSummary, ...]` and `.open(analysis_id) -> ProjectedRun`.
- `AnalysisManifest` is a strict API-internal model containing `analysis_id`, `status`, optional `started_at`, and native `events_path`; legacy detection uses the fixed v0.2 manifest/signature files defined by the importer plan.
- `RunSummary` contains `analysis_id`, `status`, `source_kind`, `started_at`, `turn_count`, `last_sequence`, `replay_trusted_through`, and optional `diagnostic`.

- [ ] **Step 1: Write failing catalog tests**

```python
def test_catalog_discovers_native_and_v02_runs_by_manifest(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    write_native_run(runs / "analysis-native")
    write_v02_run(runs / "analysis-legacy")
    (runs / "not-a-run").mkdir(parents=True)
    catalog = TrajectoryRunCatalog(runs, tmp_path / ".grid-agent/trajectory-cache", fake_projection_service())

    summaries = catalog.list_runs()

    assert [(item.analysis_id, item.source_kind) for item in summaries] == [
        ("analysis-native", "native"), ("analysis-legacy", "legacy-v0.2")
    ]


def test_catalog_rejects_manifest_id_directory_mismatch(tmp_path: Path) -> None:
    root = write_native_run(tmp_path / "runs/analysis-safe")
    write_json(root / "manifest.json", {"analysis_id": "../escape", "status": "completed"})
    catalog = TrajectoryRunCatalog(tmp_path / "runs", tmp_path / "cache", fake_projection_service())
    assert catalog.list_runs() == ()
    with pytest.raises(RunNotFoundError):
        catalog.open("../escape")


def test_catalog_ignores_symlinked_run_directory(tmp_path: Path) -> None:
    outside = write_native_run(tmp_path / "outside/analysis-outside")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "analysis-link").symlink_to(outside, target_is_directory=True)
    assert TrajectoryRunCatalog(runs, tmp_path / "cache", fake_projection_service()).list_runs() == ()
```

- [ ] **Step 2: Add dependencies and run the failing tests**

Run: `uv add --project packages/grid-agent 'fastapi>=0.139,<1' 'uvicorn>=0.51,<1' && uv add --project packages/grid-agent --dev 'httpx>=0.28,<1' && uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_catalog.py -q`

Expected: dependency sync succeeds; tests FAIL because catalog models do not exist.

- [ ] **Step 3: Implement manifest-bound discovery**

```python
class TrajectoryRunCatalog:
    def list_runs(self) -> tuple[RunSummary, ...]:
        summaries: list[RunSummary] = []
        root = self.runs_root.resolve(strict=True)
        for candidate in sorted(self.runs_root.iterdir()):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                resolved = candidate.resolve(strict=True)
                if resolved.parent != root:
                    continue
                manifest = AnalysisManifest.model_validate_json((resolved / "manifest.json").read_text(encoding="utf-8"))
                if manifest.analysis_id != candidate.name or not ANALYSIS_ID.fullmatch(manifest.analysis_id):
                    continue
                summaries.append(self._summary(resolved, manifest))
            except (OSError, ValidationError, ValueError):
                continue
        return tuple(sorted(summaries, key=lambda item: (item.started_at or "", item.analysis_id), reverse=True))

    def open(self, analysis_id: str) -> ProjectedRun:
        if not ANALYSIS_ID.fullmatch(analysis_id):
            raise RunNotFoundError(analysis_id)
        run_root = self.runs_root.resolve(strict=True) / analysis_id
        if run_root.is_symlink() or run_root.resolve(strict=True).parent != self.runs_root.resolve(strict=True):
            raise RunNotFoundError(analysis_id)
        return self.projection_service.open_run(run_root)
```

Use strict Pydantic manifest models for the current schema and compatible v0.2 schema. A corrupt/partial run may appear with `status="corrupt"` only after its manifest identity is safe; its diagnostic contains no absolute paths or secret content.

- [ ] **Step 4: Run focused catalog tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_catalog.py -q`

Expected: native, legacy, partial, corrupt, mismatch, traversal-like ID, and symlink discovery tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/pyproject.toml packages/grid-agent/uv.lock packages/grid-agent/src/grid_agent/application/paths.py packages/grid-agent/src/grid_agent/trajectory/api packages/grid-agent/tests/trajectory/api/test_catalog.py
git commit -m "feat: discover trajectory runs safely"
```

### Task 2: HMAC sequence cursors and bounded paging

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/cursor.py`
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/paging.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_cursor.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_paging.py`

**Interfaces:**
- Produces: `CursorCodec.load_or_create(key_path)`, `.encode(CursorState) -> str`, and `.decode(value, expected: CursorExpectation) -> CursorState`.
- `CursorState` binds `analysis_id`, `view`, `source_fingerprint`, `projection_version`, `before_sequence`, and `direction="older"`.
- `CursorExpectation` binds the same identity/version fields except `before_sequence`; it deliberately cannot weaken the sequence boundary encoded in the signed cursor.
- Produces: `ProjectionPager.page(records, *, cursor_state=None, max_records=500, max_bytes=2*1024*1024) -> ProjectionPage`.
- `ProjectionPage` contains `items`, `older_cursor`, `newer_cursor=None` in v1, `first_sequence`, `last_sequence`, `has_older`, and `encoded_bytes`.

- [ ] **Step 1: Write failing cursor/page tests**

```python
def test_cursor_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    codec = CursorCodec.load_or_create(tmp_path / "cursor.key")
    state = CursorState(
        analysis_id="analysis-test", view="business", source_fingerprint="sha256:source",
        projection_version="business-trajectory/1.0", before_sequence=800, direction="older",
    )
    encoded = codec.encode(state)
    expected = CursorExpectation(
        analysis_id=state.analysis_id,
        view=state.view,
        source_fingerprint=state.source_fingerprint,
        projection_version=state.projection_version,
        direction=state.direction,
    )
    assert codec.decode(encoded, expected=expected) == state
    replacement = "A" if encoded[-1] != "A" else "B"
    with pytest.raises(CursorError, match="tampered"):
        codec.decode(encoded[:-1] + replacement, expected=expected)


def test_cursor_rejects_foreign_run_view_and_stale_projection(tmp_path: Path) -> None:
    codec, encoded = cursor_fixture(tmp_path)
    for field, value, message in (
        ("analysis_id", "analysis-other", "foreign run"),
        ("view", "agent", "wrong view"),
        ("source_fingerprint", "sha256:new", "stale source"),
        ("projection_version", "business-trajectory/2.0", "stale projection"),
    ):
        with pytest.raises(CursorError, match=message):
            codec.decode(encoded, expected=expected_cursor(**{field: value}))


def test_page_enforces_record_and_byte_limits() -> None:
    records = tuple(page_record(sequence, payload="x" * 20_000) for sequence in range(1, 1001))
    page = ProjectionPager().page(records)
    assert len(page.items) <= 500
    assert page.encoded_bytes <= 2 * 1024 * 1024
    assert page.items[-1].sequence == 1000
    assert page.has_older is True
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_cursor.py packages/grid-agent/tests/trajectory/api/test_paging.py -q`

Expected: FAIL because cursor and pager modules do not exist.

- [ ] **Step 3: Implement signed stable cursors and tail-first pages**

```python
class CursorCodec:
    def encode(self, state: CursorState) -> str:
        body = canonical_json_bytes(state.model_dump(mode="json")).rstrip(b"\n")
        signature = hmac.digest(self._key, body, "sha256")
        return base64.urlsafe_b64encode(body + b"." + signature).decode("ascii").rstrip("=")

    def decode(self, value: str, expected: CursorExpectation) -> CursorState:
        try:
            padded = value + "=" * (-len(value) % 4)
            body, signature = base64.urlsafe_b64decode(padded).rsplit(b".", 1)
        except (ValueError, binascii.Error) as exc:
            raise CursorError("invalid cursor encoding") from exc
        if not hmac.compare_digest(signature, hmac.digest(self._key, body, "sha256")):
            raise CursorError("tampered cursor")
        state = CursorState.model_validate_json(body)
        validate_expected_cursor(state, expected)
        return state
```

Create the cursor key with `secrets.token_bytes(32)`, `os.open(..., O_CREAT|O_EXCL, 0o600)`, write/fsync, and never return it through the API. Pager starts at the tail, prepends older records by source sequence, computes each candidate's canonical encoded size before admission, and always includes at least one record or raises `ProjectionRecordTooLarge` when a single record exceeds 2 MiB.

- [ ] **Step 4: Run focused cursor/page tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_cursor.py packages/grid-agent/tests/trajectory/api/test_paging.py -q`

Expected: round-trip, key permissions, tamper, stale/foreign, tail page, prepend, 500-record, 2-MiB, and oversized-record tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/api/cursor.py packages/grid-agent/src/grid_agent/trajectory/api/paging.py packages/grid-agent/tests/trajectory/api/test_cursor.py packages/grid-agent/tests/trajectory/api/test_paging.py
git commit -m "feat: page trajectory projections by cursor"
```

### Task 3: Allowlisted artifact gateway

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/artifacts.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_artifacts.py`

**Interfaces:**
- Produces: `ArtifactGateway(run_root, artifact_index).open(artifact_ref) -> ArtifactResponse`.
- `ArtifactResponse` contains verified `path`, `media_type`, `filename`, `sha256`, and `size_bytes`.
- Allowed media types: `application/json; charset=utf-8`, `text/markdown; charset=utf-8`, and `text/plain; charset=utf-8`; raw Pi sidecars have no ArtifactIndex entry and are denied.
- Implementation imports the standard-library `stat` module and uses `stat.S_ISREG` after resolving the allowlisted path.

- [ ] **Step 1: Write failing gateway security tests**

```python
def test_gateway_opens_only_verified_indexed_artifact(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)
    response = ArtifactGateway(run_root, index).open(evidence_ref)
    assert response.path.is_file()
    assert response.media_type == "application/json; charset=utf-8"
    assert response.path.read_bytes().startswith(b"{")


@pytest.mark.parametrize("reference", ["../manifest.json", "/etc/passwd", "pi/session.jsonl", "evidence:sha256:" + "f" * 64])
def test_gateway_rejects_unregistered_reference(tmp_path: Path, reference: str) -> None:
    run_root, index, _ = artifact_fixture(tmp_path)
    with pytest.raises(ArtifactAccessError, match="not registered"):
        ArtifactGateway(run_root, index).open(reference)


def test_gateway_rejects_symlink_swap_after_projection(tmp_path: Path) -> None:
    run_root, index, evidence_ref = artifact_fixture(tmp_path)
    path = run_root / index.records[evidence_ref].relative_path
    path.unlink()
    path.symlink_to(tmp_path / "outside.json")
    with pytest.raises(ArtifactAccessError, match="safe run path"):
        ArtifactGateway(run_root, index).open(evidence_ref)
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_artifacts.py -q`

Expected: FAIL because `ArtifactGateway` does not exist.

- [ ] **Step 3: Implement ref-to-index-to-real-path verification**

```python
class ArtifactGateway:
    def open(self, artifact_ref: str) -> ArtifactResponse:
        record = self.artifact_index.records.get(artifact_ref)
        if record is None:
            raise ArtifactAccessError("artifact is not registered")
        root = self.run_root.resolve(strict=True)
        lexical = self.run_root / record.relative_path
        if lexical.is_symlink():
            raise ArtifactAccessError("artifact is not a safe run path")
        resolved = lexical.resolve(strict=True)
        if resolved.parent != root and root not in resolved.parents:
            raise ArtifactAccessError("artifact is not a safe run path")
        file_stat = resolved.stat()
        if not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactAccessError("artifact is not a regular file")
        value = resolved.read_bytes()
        if sha256(value).hexdigest() != record.sha256 or len(value) != record.size_bytes:
            raise ArtifactAccessError("artifact integrity mismatch")
        return ArtifactResponse(resolved, media_type_for(record.kind), resolved.name, record.sha256, len(value))
```

Reject encoded `/` or `\` before ref lookup, even though valid refs contain no separators. Re-open and verify at request time to catch post-projection replacement. Never expose the resolved absolute path in error bodies or response headers.

- [ ] **Step 4: Run focused gateway tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_artifacts.py -q`

Expected: indexed success, raw-sidecar denial, traversal, absolute path, encoded separator, symlink swap, device file, size, and digest tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/api/artifacts.py packages/grid-agent/tests/trajectory/api/test_artifacts.py
git commit -m "feat: restrict trajectory artifact access"
```

### Task 4: FastAPI routes and response security

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/app.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_app.py`

**Interfaces:**
- Produces: `create_trajectory_app(catalog, cursor_codec) -> FastAPI`.
- Routes: `GET /api/runs`, `GET /api/runs/{analysis_id}`, `GET /api/runs/{analysis_id}/{business|agent}`, `GET /api/runs/{analysis_id}/context?at_sequence=`, and `GET /api/runs/{analysis_id}/artifacts/{artifact_ref}`.
- Typed errors: `run_not_found` 404, `invalid_cursor` 400, `stale_cursor` 409, `projection_corrupt` 409, `artifact_not_found` 404, and `artifact_rejected` 403.

- [ ] **Step 1: Write failing endpoint/security tests**

```python
def test_api_lists_runs_and_returns_tail_business_page() -> None:
    client = TestClient(create_test_app())
    runs = client.get("/api/runs")
    page = client.get("/api/runs/analysis-test/business")
    assert runs.status_code == 200
    assert page.status_code == 200
    assert page.json()["items"][-1]["source_sequence"] == 900
    assert page.json()["older_cursor"]


def test_api_has_no_mutation_routes() -> None:
    client = TestClient(create_test_app())
    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/runs/analysis-test").status_code == 405


def test_every_response_has_browser_security_headers() -> None:
    response = TestClient(create_test_app()).get("/api/runs")
    assert response.headers["content-security-policy"] == "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_artifact_endpoint_never_serves_raw_html() -> None:
    response = TestClient(create_test_app()).get(f"/api/runs/analysis-test/artifacts/{MARKDOWN_REF}")
    assert response.headers["content-type"].startswith("text/markdown")
    assert "text/html" not in response.headers["content-type"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py -q`

Expected: FAIL because the FastAPI app does not exist.

- [ ] **Step 3: Implement fixed GET routes and middleware**

```python
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_trajectory_app(catalog: TrajectoryRunCatalog, cursor_codec: CursorCodec) -> FastAPI:
    app = FastAPI(title="grid-agent trajectory", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    @app.get("/api/runs", response_model=RunListResponse)
    def list_runs() -> RunListResponse:
        return RunListResponse(items=catalog.list_runs())

    @app.get("/api/runs/{analysis_id}/business", response_model=ProjectionPage)
    def business_page(analysis_id: str, cursor: str | None = None) -> ProjectionPage:
        projected = catalog.open(analysis_id)
        return page_view(projected, "business", cursor, cursor_codec)

    return app
```

Add the remaining fixed routes with explicit `response_model`s and exception handlers that return `ApiError(code, message)` without stack traces or absolute paths. Context requires an integer sequence ≥1. Artifact response uses `FileResponse` with the gateway's fixed media type and a sanitized basename-only filename. Do not install CORSMiddleware.

- [ ] **Step 4: Run focused app tests**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py -q`

Expected: endpoint, pagination, typed error, no-mutation, no-CORS, fixed-content-type, security-header, partial/corrupt/unsupported, and OpenAPI method tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/api/app.py packages/grid-agent/tests/trajectory/api/test_app.py
git commit -m "feat: expose read-only trajectory API"
```

### Task 5: Loopback server, CLI, Makefile, and operator docs

**Files:**
- Create: `packages/grid-agent/src/grid_agent/trajectory/api/server.py`
- Create: `packages/grid-agent/tests/trajectory/api/test_server.py`
- Modify: `packages/grid-agent/src/grid_agent/cli/app.py`
- Modify: `packages/grid-agent/tests/cli/test_app.py`
- Modify: `Makefile`
- Modify: `docs/RUNBOOK.md`
- Modify: `docs/MANUAL-VALIDATION.md`

**Interfaces:**
- CLI: `grid-agent trajectory serve --host 127.0.0.1 --port 8765 --runs-root runs`.
- Make: `make trajectory PORT=8765`.
- Produces: `serve_trajectory(project_paths, *, host, port, runs_root) -> None`.
- First release accepts `127.0.0.1`, `::1`, and `localhost`; all other hosts fail before uvicorn starts.

- [ ] **Step 1: Write failing server/CLI tests**

```python
@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com"])
def test_server_rejects_non_loopback_host(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        build_server_config(ProjectPaths.from_root(tmp_path), host=host, port=8765, runs_root=tmp_path / "runs")


def test_trajectory_serve_delegates_without_answer_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {}
    monkeypatch.setattr("grid_agent.cli.app.serve_trajectory", lambda **kwargs: observed.update(kwargs))
    result = CliRunner().invoke(app, ["trajectory", "serve", "--port", "9000"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert observed["port"] == 9000


def test_trajectory_cli_reports_startup_errors_on_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("grid_agent.cli.app.serve_trajectory", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("missing assets")))
    result = CliRunner().invoke(app, ["trajectory", "serve"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "missing assets" in result.stderr
```

- [ ] **Step 2: Run and confirm failures**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_server.py packages/grid-agent/tests/cli/test_app.py -q`

Expected: FAIL because the server builder and Typer subapp do not exist.

- [ ] **Step 3: Implement server config and Typer subapp**

```python
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def serve_trajectory(*, project_paths: ProjectPaths, host: str, port: int, runs_root: Path) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError("trajectory server host must be loopback")
    catalog = TrajectoryRunCatalog(
        runs_root=runs_root,
        cache_root=project_paths.trajectory_cache_dir,
        projection_service=ProjectionService(project_paths.trajectory_cache_dir),
    )
    codec = CursorCodec.load_or_create(project_paths.trajectory_cache_dir / "cursor.key")
    uvicorn.run(create_trajectory_app(catalog, codec), host=host, port=port, log_config=None, access_log=False)
```

```python
trajectory_app = typer.Typer(help="Inspect agent and business trajectories.")
app.add_typer(trajectory_app, name="trajectory")


@trajectory_app.command("serve")
def trajectory_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port", min=1, max=65535),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
) -> None:
    try:
        serve_trajectory(project_paths=ProjectPaths.from_root(Path.cwd()), host=host, port=port, runs_root=runs_root)
    except Exception as exc:
        typer.echo(f"grid-agent trajectory error: {exc}", err=True)
        raise typer.Exit(1)
```

Add a `trajectory` Make target that invokes the command with `PORT ?= 8765`. Document startup, loopback-only behavior, all read-only endpoints, artifact denial, and Ctrl-C shutdown. Manual validation must use `curl -i` to inspect CSP/content types and verify POST returns 405.

- [ ] **Step 4: Run API/CLI/docs gates**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api packages/grid-agent/tests/cli/test_app.py -q && make doctor`

Expected: API/CLI tests pass and doctor remains successful.

- [ ] **Step 5: Commit**

```bash
git add packages/grid-agent/src/grid_agent/trajectory/api/server.py packages/grid-agent/tests/trajectory/api/test_server.py packages/grid-agent/src/grid_agent/cli/app.py packages/grid-agent/tests/cli/test_app.py Makefile docs/RUNBOOK.md docs/MANUAL-VALIDATION.md
git commit -m "feat: serve trajectory API on loopback"
```

### Task 6: Read-only API regression gate

**Files:**
- Verify only: Tasks 1–5 outputs.

**Interfaces:**
- Produces verification evidence only.

- [ ] **Step 1: Run the complete API/security suite**

Run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api -q`

Expected: all catalog, cursor, paging, artifact, endpoint, and server tests pass.

- [ ] **Step 2: Verify OpenAPI contains only allowed methods**

Add `test_openapi_exposes_only_get_methods` to `packages/grid-agent/tests/trajectory/api/test_app.py`, collecting every key under `create_test_app().openapi()["paths"]` and asserting the set equals `{"get"}`. Then run: `uv run --project packages/grid-agent pytest packages/grid-agent/tests/trajectory/api/test_app.py -q -k openapi_exposes_only_get_methods`

Expected: the named test passes and proves no mutation or WebSocket operation is advertised.

- [ ] **Step 3: Run existing project gates serially**

Run: `make test && make test-e2e && make validate`

Expected: all existing and trajectory tests pass; answer-producing stdout and evidence contracts do not regress.

- [ ] **Step 4: Inspect the commit boundary**

Run: `git status --short && git log --oneline -6`

Expected: no uncommitted implementation changes; five task commits are visible. Do not create an empty verification commit.

## Self-Review

- Spec coverage: safe discovery, native/legacy opening, stable sequence cursors, 500-record/2-MiB bounds, typed cursor errors, loopback default, run identity, allowlisted artifacts, traversal/symlink/device rejection, fixed content types, CSP, no mutation, and CLI/Make entry points are covered.
- Deferred intentionally: static Workbench assets and browser behavior belong to the UI plan; live streaming remains out of scope.
- Type consistency: API response models are the source for the TypeScript types consumed by the Workbench plan.
