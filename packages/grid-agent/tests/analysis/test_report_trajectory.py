from __future__ import annotations

from grid_agent.analysis.report_trajectory import (
    TraceDecision,
    TraceStep,
    render_analysis_trajectory,
)


def step(
    capability: str,
    *,
    args: dict[str, object],
    result: dict[str, object],
    ok: bool = True,
    sequence: int = 1,
) -> TraceStep:
    return TraceStep(
        sequence=sequence,
        turn_id="analysis-test-t001",
        tool_call_id=f"call-{sequence}",
        capability=capability,
        args=args,
        result=result,
        ok=ok,
        duration_seconds=1.25,
    )


def test_trajectory_explains_work_inputs_and_diagnostic_results() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "topology.branch.endpoints.get",
                args={"branch_kind": "line", "branch_id": 11},
                result={"from_bus": 6, "to_bus": 11},
                sequence=1,
            ),
            step(
                "analysis.powerflow.ac.run",
                args={"operation": "powerflow.ac"},
                result={
                    "converged": True,
                    "total_active_loss": {"value": 43.6275, "unit": "MW"},
                },
                sequence=2,
            ),
            step(
                "model.dataset.query",
                args={
                    "dataset": "result.res_line",
                    "order_by": [{"field": "loading_percent", "direction": "desc"}],
                    "limit": 5,
                },
                result={
                    "rows": [{"line": 17, "loading_percent": 132.51}],
                    "row_count": 5,
                },
                sequence=3,
            ),
        )
    )
    text = "\n".join(lines)
    assert "核查线路 11 两端母线" in text
    assert "母线 6 → 母线 11" in text
    assert "交流潮流" in text and "收敛" in text and "43.6275 MW" in text
    assert "result.res_line" in text
    assert "loading_percent 降序" in text
    assert "前 5 项" in text
    assert "线路 17：132.51%" in text
    assert "```json" not in text


def test_trajectory_preserves_contingency_and_violation_diagnostics() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "analysis.contingency.n_minus_one.run",
                args={"outage_kind": "single_branch", "branch_id": 17},
                result={
                    "status": "partial",
                    "scenario_count": 35,
                    "converged_scenarios": 34,
                    "worst_loading_percent": 132.51,
                },
                sequence=1,
            ),
            step(
                "analysis.result.violations.evaluate",
                args={"quantities": ["bus.vm_pu", "branch.loading_percent"]},
                result={
                    "status": "succeeded",
                    "summary": {
                        "constraint_source": "model",
                        "violation_count": 1,
                        "unavailable_quantities": [],
                    },
                },
                sequence=2,
            ),
        )
    )
    text = "\n".join(lines)
    assert "35 个场景" in text and "34 个收敛" in text
    assert "部分完成" in text and "132.51%" in text
    assert "模型约束" in text and "1 项越限" in text


def test_unknown_capability_uses_bounded_scalar_summary_and_redacts_internals() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "analysis.future.operation",
                args={
                    "subject": "line-17",
                    "mode": "screen",
                    "result_ref": "result:sha256:" + "1" * 64,
                    "access_token": "must-not-leak",
                },
                result={
                    "novel_metric": 12.75,
                    "unit": "kV",
                    "private_key": "must-not-leak",
                    "rows": list(range(100)),
                },
            ),
        )
    )
    text = "\n".join(lines)
    assert "analysis.future.operation" in text
    assert "subject=line-17" in text and "mode=screen" in text
    assert "novel_metric=12.75" in text and "unit=kV" in text
    assert "must-not-leak" not in text
    assert "result:sha256:" not in text
    assert len(text.splitlines()) <= 3


def test_task2_does_not_hide_late_nonconverged_or_failed_milestones() -> None:
    lines = render_analysis_trajectory(
        tuple(
            step(
                "analysis.powerflow.ac.run",
                args={"operation": f"powerflow.ac.{sequence}"},
                result={
                    "converged": sequence != 8,
                    "total_active_loss": {"value": sequence, "unit": "MW"},
                },
                ok=sequence != 9,
                sequence=sequence,
            )
            for sequence in range(1, 10)
        )
    )
    text = "\n".join(lines)
    assert text.count("运行交流潮流计算") == 9
    assert "8 MW" in text and "未收敛" in text
    assert "9 MW" in text and "返回受限/错误" in text
    assert "压缩" not in text


def test_fallback_sanitizes_sensitive_values_under_innocuous_keys() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "analysis.future.operation",
                args={
                    "subject": "line-17 Authorization: Bearer sk-secret-value",
                    "mode": "screen",
                },
                result={
                    "message": (
                        "failed with Bearer token-abc123 and private key abc; "
                        "asset:line:sha256:" + "3" * 64
                    ),
                    "label": "线路 17 电压正常",
                },
            ),
        ),
        decisions=(
            TraceDecision(
                turn_id="analysis-test-t001",
                tool_call_id="call-1",
                intent="inspect Authorization: Bearer hidden-value",
                decision="继续使用线路 17 电压结果",
                next_action="avoid token=hidden",
            ),
        ),
    )
    text = "\n".join(lines)
    assert "Authorization" not in text
    assert "Bearer" not in text
    assert "sk-secret-value" not in text
    assert "token-abc123" not in text
    assert "private key abc" not in text
    assert "asset:line:sha256:" not in text
    assert "hidden-value" not in text
    assert "token=hidden" not in text
    assert "线路 17 电压正常" in text
    assert "继续使用线路 17 电压结果" in text


def test_row_summary_preserves_zero_line_and_bus_ids() -> None:
    line_lines = render_analysis_trajectory(
        (
            step(
                "model.dataset.query",
                args={"dataset": "result.res_line"},
                result={"rows": [{"line": 0, "branch": 17, "loading_percent": 12.5}]},
            ),
        )
    )
    bus_lines = render_analysis_trajectory(
        (
            step(
                "model.dataset.query",
                args={"dataset": "result.res_bus"},
                result={"rows": [{"bus": 0, "bus_id": 18, "vm_pu": 1.01}]},
            ),
        )
    )
    assert "线路 0：12.5%" in "\n".join(line_lines)
    assert "线路 17" not in "\n".join(line_lines)
    assert "母线 0：1.01 p.u." in "\n".join(bus_lines)
    assert "母线 18" not in "\n".join(bus_lines)
