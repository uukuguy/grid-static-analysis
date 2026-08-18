from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class VerifiedArtifact:
    reference: str
    kind: Literal["context", "result", "evidence"]
    document: Mapping[str, Any]
    path: Path


@dataclass(frozen=True, slots=True)
class VerifiedReferenceSet:
    context: tuple[VerifiedArtifact, ...] = ()
    results: tuple[VerifiedArtifact, ...] = ()
    evidence: tuple[VerifiedArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceDiagnostic:
    category: str
    severity: Literal["warning", "error"]
    reference: str
    message: str
    impact: str
    remediation: str


class SimulatorIntegrityError(RuntimeError):
    """A successful simulator response cannot be trusted for a later turn."""


class ContentReferenceVerifier:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.evidence_root = workspace_root / "evidence"

    def verify_context(self, reference: str) -> VerifiedArtifact:
        digest = _reference_digest(reference, "context", label="context_ref")
        path = self.evidence_root / "contexts" / f"{digest}.json"
        if not path.is_file():
            raise SimulatorIntegrityError(f"context_ref is not in the current run: {reference}")
        document = _load_json_mapping(path, "context document")
        if _sha256_canonical_json(document) != digest:
            raise SimulatorIntegrityError(f"context document digest content does not match reference: {reference}")
        revision_ref = document.get("revision_ref")
        if not isinstance(revision_ref, str):
            raise SimulatorIntegrityError(f"context document is missing revision_ref: {reference}")
        self._verify_revision(revision_ref)
        return VerifiedArtifact(reference=reference, kind="context", document=document, path=path)

    def verify_result(self, reference: str) -> VerifiedArtifact:
        digest = _reference_digest(reference, "result", label="declared result_ref")
        path = _allowed_result_document_path(self.evidence_root, digest)
        if path is None:
            raise SimulatorIntegrityError(f"declared result_ref is not in the current run: {reference}")
        document = _load_json_mapping(path, "declared result document")
        _verify_result_document(reference, digest, document)
        return VerifiedArtifact(reference=reference, kind="result", document=document, path=path)

    def verify_evidence(self, reference: str) -> VerifiedArtifact:
        digest = _reference_digest(reference, "evidence", label="claimed evidence ref")
        path = _allowed_evidence_document_path(self.evidence_root, digest)
        if path is None:
            raise SimulatorIntegrityError(f"claimed evidence ref is not in the current run: {reference}")
        document = _load_json_mapping(path, "claimed evidence document")
        _verify_evidence_document(reference, digest, path, document)
        return VerifiedArtifact(reference=reference, kind="evidence", document=document, path=path)

    def audit_answer_references(
        self,
        claim_evidence_refs: tuple[str, ...],
        result_refs: tuple[str, ...],
    ) -> tuple[ReferenceDiagnostic, ...]:
        diagnostics: list[ReferenceDiagnostic] = []
        evidence_documents: list[Mapping[str, Any]] = []
        evidence_error = False
        for evidence_ref in claim_evidence_refs:
            try:
                evidence_documents.append(self.verify_evidence(evidence_ref).document)
            except RuntimeError as exc:
                evidence_error = True
                diagnostics.append(_diagnostic("missing_evidence", "error", evidence_ref, str(exc)))

        validated_result_refs: list[str] = []
        for result_ref in result_refs:
            if not result_ref.startswith("result:sha256:"):
                diagnostics.append(
                    _diagnostic(
                        "misclassified_result_ref",
                        "warning",
                        result_ref,
                        f"result_refs contains a non-result reference: {result_ref}",
                    )
                )
                continue
            validated_result_refs.append(result_ref)

        result_documents: dict[str, Mapping[str, Any]] = {}
        result_error = False
        for result_ref in validated_result_refs:
            try:
                result_documents[result_ref] = self.verify_result(result_ref).document
            except RuntimeError as exc:
                result_error = True
                diagnostics.append(_diagnostic("invalid_result", "error", result_ref, str(exc)))

        if not evidence_error and not result_error:
            try:
                self._verify_result_evidence_links(
                    tuple(validated_result_refs),
                    result_documents,
                    claim_evidence_refs,
                    tuple(evidence_documents),
                )
            except RuntimeError as exc:
                diagnostics.append(_diagnostic("unlinked_result", "error", "", str(exc)))
        return tuple(diagnostics)

    def admit_successful_tool_references(
        self,
        capability: str,
        result: Mapping[str, Any],
        evidence_refs: tuple[str, ...],
    ) -> VerifiedReferenceSet:
        contexts: dict[str, VerifiedArtifact] = {}
        results: dict[str, VerifiedArtifact] = {}
        evidence: dict[str, VerifiedArtifact] = {}

        for result_ref in _tool_result_refs(result):
            artifact = self.verify_result(result_ref)
            results[result_ref] = artifact
            self._admit_result_linked_artifacts(artifact, results, contexts, evidence)

        for evidence_ref in evidence_refs + tuple(_tool_evidence_refs(result)):
            artifact = self.verify_evidence(evidence_ref)
            evidence[evidence_ref] = artifact
            self._admit_evidence_linked_artifacts(artifact, results, contexts)

        context_ref = result.get("context_ref")
        if isinstance(context_ref, str):
            contexts[context_ref] = self.verify_context(context_ref)

        if capability == "context.open":
            opened_context_ref = result.get("context_ref")
            if isinstance(opened_context_ref, str):
                contexts[opened_context_ref] = self.verify_context(opened_context_ref)

        return VerifiedReferenceSet(
            context=tuple(contexts.values()),
            results=tuple(results.values()),
            evidence=tuple(evidence.values()),
        )

    def _verify_revision(self, reference: str) -> Mapping[str, Any]:
        digest = _reference_digest(reference, "revision", label="revision_ref")
        path = self.evidence_root / "models" / f"{digest}.json"
        if not path.is_file():
            raise SimulatorIntegrityError(f"revision_ref is not in the current run: {reference}")
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise SimulatorIntegrityError(f"revision document could not be read: {path.name}") from exc
        if hashlib.sha256(payload).hexdigest() != digest:
            raise SimulatorIntegrityError(f"revision document digest content does not match reference: {reference}")
        return _loads_json_mapping(payload.decode("utf-8"), path.name, "revision document")

    def _admit_result_linked_artifacts(
        self,
        artifact: VerifiedArtifact,
        results: dict[str, VerifiedArtifact],
        contexts: dict[str, VerifiedArtifact],
        evidence: dict[str, VerifiedArtifact],
    ) -> None:
        context_ref = artifact.document.get("context_ref")
        if isinstance(context_ref, str):
            contexts[context_ref] = self.verify_context(context_ref)
        for evidence_ref in _string_items(artifact.document.get("evidence_refs")):
            evidence[evidence_ref] = self.verify_evidence(evidence_ref)
        for scenario_ref in _scenario_result_refs(artifact.document):
            scenario = self.verify_result(scenario_ref)
            self._verify_matching_context(scenario_ref, scenario.document, artifact.document)
            results[scenario_ref] = scenario

    def _admit_evidence_linked_artifacts(
        self,
        artifact: VerifiedArtifact,
        results: dict[str, VerifiedArtifact],
        contexts: dict[str, VerifiedArtifact],
    ) -> None:
        result_ref = artifact.document.get("result_ref")
        if isinstance(result_ref, str) and result_ref.startswith("result:sha256:"):
            result = self.verify_result(result_ref)
            self._verify_matching_context(result_ref, result.document, artifact.document)
            results[result_ref] = result
        context_ref = artifact.document.get("context_ref")
        if isinstance(context_ref, str):
            contexts[context_ref] = self.verify_context(context_ref)

    def _verify_result_evidence_links(
        self,
        result_refs: tuple[str, ...],
        result_documents: Mapping[str, Mapping[str, Any]],
        claimed_evidence_refs: tuple[str, ...],
        evidence_documents: tuple[Mapping[str, Any], ...],
    ) -> None:
        """Verify explicit primary results and evidence-associated results.

        The final answer audit remains advisory and does not require the model to
        repeat result refs that are already cryptographically linked by analysis
        evidence.  It does verify any linked current-run results it discovers.
        """
        documents = dict(result_documents)
        linked: set[str] = set()
        claimed = set(claimed_evidence_refs)
        for document in evidence_documents:
            evidence_type = document.get("evidence_type")
            evidence_result_ref = document.get("result_ref")
            if isinstance(evidence_result_ref, str) and evidence_type in {"analysis_result", "contingency_scenario"}:
                if evidence_result_ref not in documents:
                    documents[evidence_result_ref] = self.verify_result(evidence_result_ref).document
                self._verify_matching_context(evidence_result_ref, documents[evidence_result_ref], document)
                linked.add(evidence_result_ref)

        for result_ref, result_document in documents.items():
            result_evidence_refs = result_document.get("evidence_refs")
            if isinstance(result_evidence_refs, list) and any(ref in claimed for ref in result_evidence_refs):
                linked.add(result_ref)

        for result_ref, result_document in documents.items():
            for evidence_document in self._current_run_analysis_evidence_for_result(result_ref):
                self._verify_matching_context(result_ref, result_document, evidence_document)
                linked.add(result_ref)
            for scenario_ref in _scenario_result_refs(result_document):
                scenario_document = self.verify_result(scenario_ref).document
                for evidence_document in self._current_run_analysis_evidence_for_result(scenario_ref):
                    self._verify_matching_context(scenario_ref, scenario_document, evidence_document)
                    self._verify_matching_context(result_ref, result_document, evidence_document)
                    linked.add(result_ref)

        for result_ref in result_refs:
            if result_ref not in linked:
                raise SimulatorIntegrityError(f"declared result_ref is not linked to claimed evidence: {result_ref}")

    def _current_run_analysis_evidence_for_result(self, result_ref: str) -> tuple[Mapping[str, Any], ...]:
        documents: list[Mapping[str, Any]] = []
        for path in (self.evidence_root / "analysis").glob("analysis-evidence-*.json"):
            document = _load_json_mapping(path, "claimed evidence document")
            if document.get("result_ref") != result_ref:
                continue
            digest = path.stem.removeprefix("analysis-evidence-")
            evidence_ref = f"evidence:sha256:{digest}"
            _verify_evidence_document(evidence_ref, digest, path, document)
            documents.append(document)
        return tuple(documents)

    def _verify_matching_context(
        self,
        result_ref: str,
        result_document: Mapping[str, Any],
        evidence_document: Mapping[str, Any],
    ) -> None:
        if (
            evidence_document.get("context_ref") != result_document.get("context_ref")
            or evidence_document.get("revision_ref") != result_document.get("revision_ref")
        ):
            raise SimulatorIntegrityError(f"declared result_ref context does not match claimed evidence: {result_ref}")


def _diagnostic(category: str, severity: Literal["warning", "error"], reference: str, message: str) -> ReferenceDiagnostic:
    if category == "misclassified_result_ref":
        return ReferenceDiagnostic(
            category=category,
            severity=severity,
            reference=reference,
            message=message,
            impact="This reference is not a simulator result and was not validated as one.",
            remediation="Use a result:sha256: reference when declaring simulator results.",
        )
    if category == "missing_evidence":
        return ReferenceDiagnostic(
            category=category,
            severity=severity,
            reference=reference,
            message=message,
            impact="The submitted answer includes evidence that could not be verified in the current run.",
            remediation="Reference a digest-verified evidence document from this run.",
        )
    if category == "invalid_result":
        return ReferenceDiagnostic(
            category=category,
            severity=severity,
            reference=reference,
            message=message,
            impact="The submitted answer declares a simulator result that could not be verified in the current run.",
            remediation="Reference a digest-verified result document from this run.",
        )
    return ReferenceDiagnostic(
        category=category,
        severity=severity,
        reference=reference,
        message=message,
        impact="The submitted answer's evidence and result references are not consistently linked.",
        remediation="Declare only current-run results linked to the claimed evidence.",
    )


def _reference_digest(reference: str, kind: str, *, label: str) -> str:
    prefix = f"{kind}:sha256:"
    if not reference.startswith(prefix):
        raise SimulatorIntegrityError(f"{label} is invalid: {reference}")
    digest = reference.removeprefix(prefix)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SimulatorIntegrityError(f"{label} is invalid: {reference}")
    return digest


def _allowed_evidence_document_path(evidence_root: Path, digest: str) -> Path | None:
    candidates = (
        evidence_root / "network-facts" / f"network-fact-{digest}.json",
        evidence_root / "analysis" / f"analysis-evidence-{digest}.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def _allowed_result_document_path(evidence_root: Path, digest: str) -> Path | None:
    candidates = (
        evidence_root / "results" / f"result-{digest}.json",
        evidence_root / "results" / f"powerflow-{digest}.json",
        evidence_root / "results" / f"contingency-{digest}.json",
        evidence_root / "results" / f"contingency-scenario-{digest}.json",
    )
    return next((path for path in candidates if path.is_file()), None)


def _load_json_mapping(path: Path, description: str) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SimulatorIntegrityError(f"{description} is not UTF-8 JSON: {path.name}") from exc
    except OSError as exc:
        raise SimulatorIntegrityError(f"{description} could not be read: {path.name}") from exc
    return _loads_json_mapping(text, path.name, description)


def _loads_json_mapping(text: str, name: str, description: str) -> Mapping[str, Any]:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SimulatorIntegrityError(f"{description} is not valid JSON: {name}") from exc
    if not isinstance(document, Mapping):
        raise SimulatorIntegrityError(f"{description} is malformed: {name}")
    return document


def _verify_evidence_document(reference: str, digest: str, path: Path, document: Mapping[str, Any]) -> None:
    if _sha256_canonical_json(document) != digest:
        raise SimulatorIntegrityError(f"claimed evidence document content does not match digest reference: {reference}")
    evidence_type = document.get("evidence_type")
    capability_id = document.get("capability_id")
    if path.parent.name == "network-facts":
        allowed_network_facts = {
            "topology.branch.endpoints.get",
            "model.constraints.describe",
        }
        if evidence_type != "network_fact" or capability_id not in allowed_network_facts:
            raise SimulatorIntegrityError(f"claimed evidence document type is not allowed: {reference}")
        return
    allowed_analysis = {
        ("analysis_result", "analysis.run"),
        ("analysis_result", "analysis.result.violations.evaluate"),
        ("analysis_result", "analysis.result.risk.rank"),
        ("analysis_result", "analysis.powerflow.ac.run"),
        ("contingency_scenario", "analysis.contingency.n_minus_one.run"),
        ("powerflow_non_convergence", "analysis.powerflow.ac.run"),
        ("powerflow_non_convergence", "analysis.contingency.n_minus_one.run"),
        ("powerflow_non_convergence", "analysis.run"),
    }
    if (str(evidence_type), str(capability_id)) not in allowed_analysis:
        raise SimulatorIntegrityError(f"claimed evidence document type is not allowed: {reference}")
    if evidence_type in {"analysis_result", "contingency_scenario"} and not isinstance(document.get("result_ref"), str):
        raise SimulatorIntegrityError(f"claimed analysis evidence is not linked to a result document: {reference}")


def _verify_result_document(reference: str, digest: str, document: Mapping[str, Any]) -> None:
    body = {key: value for key, value in document.items() if key != "result_ref"}
    if _sha256_canonical_json(body) != digest:
        raise SimulatorIntegrityError(f"declared result document content does not match digest reference: {reference}")
    if document.get("result_ref") != reference:
        raise SimulatorIntegrityError(f"declared result document reference does not match: {reference}")
    if not isinstance(document.get("context_ref"), str) or not isinstance(document.get("revision_ref"), str):
        raise SimulatorIntegrityError(f"declared result document is missing context references: {reference}")


def _tool_result_refs(result: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    result_ref = result.get("result_ref")
    if isinstance(result_ref, str):
        refs.append(result_ref)
    refs.extend(_string_items(result.get("result_refs")))
    return tuple(dict.fromkeys(refs))


def _tool_evidence_refs(result: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    evidence_ref = result.get("evidence_ref")
    if isinstance(evidence_ref, str):
        refs.append(evidence_ref)
    refs.extend(_string_items(result.get("evidence_refs")))
    return tuple(dict.fromkeys(refs))


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _scenario_result_refs(result_document: Mapping[str, Any]) -> tuple[str, ...]:
    scenarios = result_document.get("scenarios")
    if not isinstance(scenarios, list):
        return ()
    return tuple(
        str(scenario["scenario_result_ref"])
        for scenario in scenarios
        if isinstance(scenario, Mapping) and isinstance(scenario.get("scenario_result_ref"), str)
    )


def _sha256_canonical_json(document: object) -> str:
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
