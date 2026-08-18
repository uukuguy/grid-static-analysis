from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from grid_simulator.evidence import canonical_json, fingerprint, write_json, write_network
from grid_simulator.model_catalog import load_model_catalog
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
    factory: str
    engine: Literal["pandapower"] = "pandapower"
    engine_version: Literal["3.4.0"] = "3.4.0"


class OpenedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_ref: str
    model_id: str
    revision_ref: str
    engine: Literal["pandapower"]
    engine_version: Literal["3.4.0"]


def _registered_models() -> tuple[RegisteredModel, ...]:
    return tuple(
        RegisteredModel(
            model_id=str(row["model_id"]),
            title=str(row["title"]),
            aliases=tuple(str(alias) for alias in row["aliases"]),
            source=str(row["source"]),
            factory=str(row["factory"]),
        )
        for row in load_model_catalog()
    )


class ModelRegistry:
    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._models = _registered_models()
        self._by_id = {model.model_id: model for model in self._models}
        self._trusted_revisions: dict[str, str] = {}

    def list(self) -> tuple[RegisteredModel, ...]:
        return self._models

    def open(self, model_id: str) -> tuple[RegisteredModel, Any]:
        model = self.get(model_id)
        return model, self._engine.open_registered(model.factory)

    def get(self, model_id: str) -> RegisteredModel:
        model = self._by_id.get(model_id)
        if model is None:
            raise ModelNotFoundError(model_id)
        return model

    def trusted_revision_ref(self, model_id: str) -> str:
        model = self._by_id.get(model_id)
        if model is None:
            raise ModelNotFoundError(model_id)
        revision_ref = self._trusted_revisions.get(model.model_id)
        if revision_ref is None:
            net = self._engine.open_registered(model.factory)
            revision_ref = f"revision:sha256:{fingerprint(self._engine.serialize(net))}"
            self._trusted_revisions[model.model_id] = revision_ref
        return revision_ref


class ContextStore:
    def __init__(self, workspace: SimulatorWorkspace, registry: ModelRegistry) -> None:
        self._workspace = workspace
        self._registry = registry
        self._engine = registry._engine

    def create(self, model_id: str) -> OpenedContext:
        model, net = self._registry.open(model_id)
        serialized = self._engine.serialize(net)
        revision_ref = self._registry.trusted_revision_ref(model.model_id)
        if revision_ref != f"revision:sha256:{fingerprint(serialized)}":
            raise ContextIntegrityError("registered model serialization does not match trusted revision")
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
        try:
            return self._engine.deserialize(payload)
        except Exception as exc:
            raise ContextIntegrityError("model artifact is not valid pandapower JSON") from exc

    def _verify_metadata(self, context: OpenedContext) -> None:
        if context.engine != self._engine.name or context.engine_version != self._engine.version:
            raise ContextIntegrityError("context engine metadata does not match runtime")
        try:
            expected_revision_ref = self._registry.trusted_revision_ref(context.model_id)
        except ModelNotFoundError as exc:
            raise ContextIntegrityError("context model is not registered") from exc
        if context.revision_ref != expected_revision_ref:
            raise ContextIntegrityError("context revision does not match registered model")

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
