"""Models exposed by the trajectory API catalog."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AnalysisManifest(_StrictModel):
    """Validated native manifest identity and trajectory location."""

    model_config = ConfigDict(extra="allow", frozen=True, strict=True)

    schema_version: str | None = None
    analysis_id: str = Field(min_length=1)
    question_id: str | None = None
    status: str = Field(min_length=1)
    started_at: str | None = None
    events_path: str = "events/run-events.jsonl"
    completed_turns: int | None = Field(default=None, ge=0)
    total_turns: int | None = Field(default=None, ge=0)
    report_path: str | None = None
    context_path: str | None = None
    context_events_path: str | None = None
    context_available: bool | None = None
    trajectory_schema_version: str | None = None
    error: str | None = None


class LegacyV02Manifest(BaseModel):
    """The compatible identity subset of an immutable v0.2 manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    analysis_id: str = Field(min_length=1)
    status: str | None = None
    started_at: str | None = None
    total_turns: int | None = Field(default=None, ge=0)


class RunSummary(_StrictModel):
    analysis_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    started_at: str | None = None
    turn_count: int = Field(ge=0)
    last_sequence: int | None = Field(default=None, ge=0)
    replay_trusted_through: int | None = Field(default=None, ge=0)
    diagnostic: str | None = None


__all__ = ["AnalysisManifest", "LegacyV02Manifest", "RunSummary"]
