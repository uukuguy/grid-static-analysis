from __future__ import annotations

import json
from pathlib import Path

from grid_agent.validation.corpus import evaluate_corpus_trace, load_answer_corpus
from grid_agent.validation.oracles import ToolResultEvent


def _write_corpus(path: Path) -> Path:
    records = [
        {
            "record_type": "answer",
            "id": "T-A1",
            "section_id": "A",
            "section_name": "static",
            "content_markdown": "| 指标 | 结果 |\n| --- | ---: |\n| 数量 | 39 |",
        },
        {
            "record_type": "answer",
            "id": "T-F1",
            "section_id": "F",
            "section_name": "short circuit",
            "content_markdown": "| index | `ikss_ka` |\n| ---: | ---: |\n| 0 | 26.243194 |",
        },
    ]
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")
    return path


def test_answer_corpus_loads_metric_and_row_oriented_tables(tmp_path: Path) -> None:
    corpus = load_answer_corpus(_write_corpus(tmp_path / "answers.jsonl"))

    assert corpus.require("T-A1").expected({"metric": "数量"}) == "39"
    assert corpus.require("T-F1").expected({"row": 0, "column": "ikss_ka"}) == "26.243194"


def test_corpus_trace_oracle_uses_typed_values_and_numeric_tolerance(tmp_path: Path) -> None:
    corpus = load_answer_corpus(_write_corpus(tmp_path / "answers.jsonl"))
    events = (
        ToolResultEvent(
            capability="model.dataset.query",
            result={"returned_row_count": 39},
            evidence_refs=(),
        ),
    )

    errors = evaluate_corpus_trace(
        events,
        {
            "corpus_id": "T-A1",
            "checks": [
                {
                    "capability": "model.dataset.query",
                    "actual_path": "returned_row_count",
                    "expected": {"metric": "数量"},
                    "comparator": "integer",
                }
            ],
        },
        corpus,
    )

    assert errors == ()


def test_corpus_trace_oracle_rejects_semantic_mismatch_even_with_successful_event(tmp_path: Path) -> None:
    corpus = load_answer_corpus(_write_corpus(tmp_path / "answers.jsonl"))
    events = (
        ToolResultEvent(
            capability="analysis.run",
            result={"summary": {"ikss_ka": 25.0}},
            evidence_refs=(),
        ),
    )

    errors = evaluate_corpus_trace(
        events,
        {
            "corpus_id": "T-F1",
            "checks": [
                {
                    "capability": "analysis.run",
                    "actual_path": "summary.ikss_ka",
                    "expected": {"row": 0, "column": "ikss_ka"},
                    "comparator": "number",
                    "tolerance": 1e-6,
                }
            ],
        },
        corpus,
    )

    assert errors and "semantic mismatch" in errors[0]
