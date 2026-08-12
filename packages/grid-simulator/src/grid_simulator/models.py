from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from grid_simulator.evidence import canonical_json, fingerprint, write_json, write_network
from grid_simulator.workspace import SimulatorWorkspace


CONTEXT_REF_PATTERN = re.compile(r"^context:sha256:([0-9a-f]{64})$")
REVISION_REF_PATTERN = re.compile(r"^revision:sha256:([0-9a-f]{64})$")


class ModelNotFoundError(Exception):
    def __init__(self, model_id: str) -> None:
        super().__init__("model is not registered")
        self.model_id = model_id


class InvalidContextRef(Exception):
    pass


class ContextNotFoundError(Exception):
    pass


class ContextIntegrityError(Exception):
    pass


class RegisteredModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    title: str
    aliases: tuple[str, ...]
    source: str
    engine: Literal["pandapower"] = "pandapower"
    engine_version: Literal["3.4.0"] = "3.4.0"


class OpenedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_ref: str
    model_id: str
    revision_ref: str
    engine: Literal["pandapower"]
    engine_version: Literal["3.4.0"]


_IEEE39 = RegisteredModel(
    model_id="ieee39",
    title="IEEE 39-bus system",
    aliases=("IEEE-39节点系统", "IEEE 39 bus system", "New England 39-bus system"),
    source="pandapower.networks.case39",
)


class ModelRegistry:
    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._models = (_IEEE39,)
        self._by_id = {model.model_id: model for model in self._models}

    def list(self) -> tuple[RegisteredModel, ...]:
        return self._models

    def open(self, model_id: str) -> tuple[RegisteredModel, Any]:
        model = self._by_id.get(model_id)
        if model is None:
            raise ModelNotFoundError(model_id)
        return model, self._engine.open_registered(model.model_id)


class ContextStore:
    def __init__(self, workspace: SimulatorWorkspace, registry: ModelRegistry) -> None:
        self._workspace = workspace
        self._registry = registry
        self._engine = registry._engine

    def create(self, model_id: str) -> OpenedContext:
        model, net = self._registry.open(model_id)
        serialized = self._engine.serialize(net)
        revision_digest = fingerprint(serialized)
        revision_ref = f"revision:sha256:{revision_digest}"
        document = {
            "model_id": model.model_id,
            "revision_ref": revision_ref,
            "engine": model.engine,
            "engine_version": model.engine_version,
        }
        context_ref = f"context:sha256:{fingerprint(canonical_json(document))}"
        write_network(self._workspace.model_artifact(revision_ref), serialized)
        write_json(self._workspace.context_document(context_ref), document)
        return OpenedContext(context_ref=context_ref, **document)

    def require(self, context_ref: str) -> OpenedContext:
        expected_digest = _parse_context_ref(context_ref)
        document_path = self._workspace.context_document(context_ref)
        if not document_path.is_file():
            raise ContextNotFoundError("context reference is unknown")
        payload = document_path.read_text(encoding="utf-8")
        if fingerprint(payload) != expected_digest:
            raise ContextIntegrityError("context document digest does not match reference")
        try:
            document = json.loads(payload)
            context = OpenedContext(context_ref=context_ref, **document)
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise ContextIntegrityError("context document is invalid") from exc
        self._verify_metadata(context)
        self._verify_artifact(context.revision_ref)
        return context

    def load_network(self, context_ref: str):
        context = self.require(context_ref)
        artifact_path = self._workspace.model_artifact(context.revision_ref)
        payload = artifact_path.read_text(encoding="utf-8")
        self._verify_metadata(context)
        return self._engine.deserialize(payload)

    def _verify_metadata(self, context: OpenedContext) -> None:
        if context.engine != self._engine.name or context.engine_version != self._engine.version:
            raise ContextIntegrityError("context engine metadata does not match runtime")
        if context.model_id not in {model.model_id for model in self._registry.list()}:
            raise ContextIntegrityError("context model is not registered")

    def _verify_artifact(self, revision_ref: str) -> None:
        expected_digest = _parse_revision_ref(revision_ref)
        artifact_path = self._workspace.model_artifact(revision_ref)
        if not artifact_path.is_file():
            raise ContextIntegrityError("model artifact is unavailable")
        if fingerprint(artifact_path.read_bytes()) != expected_digest:
            raise ContextIntegrityError("model artifact digest does not match revision")


def _parse_context_ref(context_ref: str) -> str:
    match = CONTEXT_REF_PATTERN.fullmatch(context_ref)
    if match is None:
        raise InvalidContextRef("context reference must be context:sha256:<64 lowercase hex>")
    return match.group(1)


def _parse_revision_ref(revision_ref: str) -> str:
    match = REVISION_REF_PATTERN.fullmatch(revision_ref)
    if match is None:
        raise ContextIntegrityError("revision reference must be revision:sha256:<64 lowercase hex>")
    return match.group(1)
