from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CapabilityFamilyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    availability: Literal["published", "not_published"]
    reason: str


CAPABILITY_FAMILIES = (
    CapabilityFamilyStatus(id="model-context", availability="published", reason="Registered immutable model contexts"),
    CapabilityFamilyStatus(id="model-data", availability="published", reason="Schema-described model data and constraints"),
    CapabilityFamilyStatus(id="topology", availability="published", reason="Read-only topology analysis"),
    CapabilityFamilyStatus(id="power-flow", availability="published", reason="AC power flow and solver diagnostics"),
    CapabilityFamilyStatus(id="result-analysis", availability="published", reason="Typed result summaries and rankings"),
    CapabilityFamilyStatus(id="contingency", availability="published", reason="Static single-branch outage analysis"),
    CapabilityFamilyStatus(id="evidence", availability="published", reason="Content-addressed result evidence"),
    CapabilityFamilyStatus(id="opf", availability="not_published", reason="No project semantic OPF capability is published"),
    CapabilityFamilyStatus(id="short-circuit", availability="not_published", reason="No project semantic short-circuit capability is published"),
    CapabilityFamilyStatus(id="state-estimation", availability="not_published", reason="No project semantic state-estimation capability is published"),
    CapabilityFamilyStatus(id="time-series", availability="not_published", reason="No project semantic time-series capability is published"),
    CapabilityFamilyStatus(id="model-lifecycle", availability="published", reason="Registered catalog, declarative creation, and immutable typed revisions"),
)
