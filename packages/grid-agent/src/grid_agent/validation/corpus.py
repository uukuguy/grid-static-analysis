from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grid_agent.validation.oracles import ToolResultEvent


class AnswerCorpusError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnswerRecord:
    identifier: str
    section_id: str
    section_name: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def expected(self, selector: dict[str, Any]) -> str:
        metric = selector.get("metric")
        if isinstance(metric, str):
            if len(self.headers) < 2:
                raise AnswerCorpusError(f"{self.identifier} has no metric/value table")
            for row in self.rows:
                if row and _clean(row[0]) == _clean(metric):
                    return row[1]
            raise AnswerCorpusError(f"{self.identifier} has no metric: {metric}")
        row_number = selector.get("row")
        column = selector.get("column")
        if isinstance(row_number, int) and isinstance(column, str):
            if row_number < 0 or row_number >= len(self.rows):
                raise AnswerCorpusError(f"{self.identifier} row is out of range: {row_number}")
            try:
                column_number = tuple(_clean(item) for item in self.headers).index(_clean(column))
            except ValueError as exc:
                raise AnswerCorpusError(f"{self.identifier} has no column: {column}") from exc
            return self.rows[row_number][column_number]
        raise AnswerCorpusError("expected selector requires metric or row/column")


class AnswerCorpus:
    def __init__(self, records: tuple[AnswerRecord, ...]) -> None:
        identifiers = [record.identifier for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise AnswerCorpusError("answer corpus ids must be unique")
        self.records = records
        self._by_id = {record.identifier: record for record in records}

    def require(self, identifier: str) -> AnswerRecord:
        try:
            return self._by_id[identifier]
        except KeyError as exc:
            raise AnswerCorpusError(f"unknown answer corpus id: {identifier}") from exc


def load_answer_corpus(path: Path) -> AnswerCorpus:
    records: list[AnswerRecord] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AnswerCorpusError(f"invalid answer corpus JSON at line {line_number}") from exc
        if not isinstance(payload, dict) or payload.get("record_type") != "answer":
            continue
        identifier = payload.get("id")
        content = payload.get("content_markdown")
        if not isinstance(identifier, str) or not isinstance(content, str):
            raise AnswerCorpusError(f"malformed answer record at line {line_number}")
        headers, rows = _parse_markdown_table(content, identifier)
        records.append(
            AnswerRecord(
                identifier=identifier,
                section_id=str(payload.get("section_id", "")),
                section_name=str(payload.get("section_name", "")),
                headers=headers,
                rows=rows,
            )
        )
    if not records:
        raise AnswerCorpusError("answer corpus contains no answer records")
    return AnswerCorpus(tuple(records))


def evaluate_corpus_trace(
    events: tuple[ToolResultEvent, ...],
    arguments: dict[str, Any],
    corpus: AnswerCorpus,
) -> tuple[str, ...]:
    corpus_id = arguments.get("corpus_id")
    checks = arguments.get("checks")
    if not isinstance(corpus_id, str) or not isinstance(checks, list):
        return ("corpus oracle requires corpus_id and checks",)
    try:
        record = corpus.require(corpus_id)
    except AnswerCorpusError as exc:
        return (str(exc),)

    errors: list[str] = []
    for check_number, raw_check in enumerate(checks, start=1):
        if not isinstance(raw_check, dict):
            errors.append(f"check {check_number} is malformed")
            continue
        capability = raw_check.get("capability")
        path = raw_check.get("actual_path")
        selector = raw_check.get("expected")
        comparator = raw_check.get("comparator", "equals")
        candidates = [event for event in events if event.capability == capability and event.ok is True]
        if not candidates:
            errors.append(f"check {check_number} missing successful capability: {capability}")
            continue
        if not isinstance(path, str) or not isinstance(selector, dict) or not isinstance(comparator, str):
            errors.append(f"check {check_number} is malformed")
            continue
        try:
            actual = _path_value(candidates[-1].result, path)
            expected = record.expected(selector)
        except (AnswerCorpusError, KeyError, IndexError, TypeError) as exc:
            errors.append(f"check {check_number} cannot resolve value: {exc}")
            continue
        tolerance = raw_check.get("tolerance", 1e-6)
        if not _matches(actual, expected, comparator, tolerance):
            errors.append(
                f"check {check_number} semantic mismatch at {capability}.{path}: "
                f"actual={actual!r}, expected={_clean(expected)!r}"
            )
    return tuple(errors)


def _parse_markdown_table(markdown: str, identifier: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    table_rows = [_split_markdown_row(line) for line in markdown.splitlines() if line.strip().startswith("|")]
    if len(table_rows) < 3 or not all(_is_separator(cell) for cell in table_rows[1]):
        raise AnswerCorpusError(f"{identifier} content_markdown has no supported table")
    headers = tuple(_clean(cell) for cell in table_rows[0])
    rows = tuple(tuple(_clean(cell) for cell in row) for row in table_rows[2:])
    if not headers or any(len(row) != len(headers) for row in rows):
        raise AnswerCorpusError(f"{identifier} table is malformed")
    return headers, rows


def _split_markdown_row(line: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in line.strip().strip("|").split("|"))


def _is_separator(value: str) -> bool:
    return re.fullmatch(r":?-{3,}:?", value.strip()) is not None


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _path_value(value: Any, path: str) -> Any:
    current = value
    for component in path.split("."):
        if isinstance(current, dict):
            current = current[component]
        elif isinstance(current, list):
            current = current[int(component)]
        else:
            raise TypeError(f"cannot traverse {component}")
    return current


def _matches(actual: Any, expected: str, comparator: str, tolerance: Any) -> bool:
    normalized = _clean(expected)
    if comparator == "number":
        try:
            return math.isclose(float(actual), float(normalized), rel_tol=0.0, abs_tol=float(tolerance))
        except (TypeError, ValueError):
            return False
    if comparator == "integer":
        try:
            return int(actual) == int(normalized)
        except (TypeError, ValueError):
            return False
    if comparator == "boolean":
        expected_bool = normalized.casefold() in {"是", "true", "yes", "收敛", "成功"}
        if isinstance(actual, bool):
            return actual is expected_bool
        actual_bool = str(actual).casefold() in {"true", "yes", "是", "succeeded", "converged", "success"}
        return actual_bool is expected_bool
    if comparator == "empty":
        expected_empty = normalized.casefold() in {"无", "none", "empty", "[]", "0"}
        actual_empty = actual is None or actual == 0 or actual == [] or actual == {}
        return expected_empty and actual_empty
    if comparator == "empty_means_true":
        expected_bool = normalized.casefold() in {"是", "true", "yes"}
        actual_empty = actual is None or actual == 0 or actual == [] or actual == {}
        return expected_bool and actual_empty
    if comparator == "equals":
        return str(actual).casefold() == normalized.casefold()
    return False
