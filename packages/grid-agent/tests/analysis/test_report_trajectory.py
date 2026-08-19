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


def test_reader_visible_scalars_neutralize_markdown_and_html_injection() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "analysis.future.`\n### injected",
                args={
                    "subject": (
                        "线路 17 电压正常 1.02 p.u.\n"
                        "### injected\n"
                        "```json\n{\"leak\": true}\n```\n"
                        "<script>alert(1)</script> [bad](javascript:alert(1))"
                    ),
                    "mode": "screen",
                },
                result={
                    "label": "母线 0 电压 1.01 p.u.\n<a href='https://bad.example'>bad</a>",
                    "novel_metric": 12.75,
                },
            ),
        ),
        decisions=(
            TraceDecision(
                turn_id="analysis-test-t001",
                tool_call_id="call-1",
                intent="compare\n### injected",
                decision="保留线路 17 电压结论\n```json\n{}",
                next_action="<b>不要生成 HTML</b>",
            ),
        ),
    )
    text = "\n".join(lines)
    assert "线路 17 电压正常 1.02 p.u." in text
    assert "母线 0 电压 1.01 p.u." in text
    assert "12.75" in text
    assert "\n### injected" not in text
    assert "```" not in text
    assert "```json" not in text
    assert "<script" not in text
    assert "</script>" not in text
    assert "<a href" not in text
    assert "</a>" not in text
    assert "<b>" not in text
    assert "[bad](javascript:alert(1))" not in text


def test_inline_code_values_neutralize_backticks_and_markdown_structure() -> None:
    lines = render_analysis_trajectory(
        (
            step(
                "model.dataset.query",
                args={
                    "dataset": "result.res_line`\n```json\n### injected",
                    "order_by": [{"field": "loading_percent`\n### injected", "direction": "desc"}],
                    "limit": 5,
                },
                result={"rows": [{"line": 17, "loading_percent": 132.51}]},
            ),
        )
    )
    text = "\n".join(lines)
    assert "result.res_line" in text
    assert "loading_percent" in text
    assert "线路 17：132.51%" in text
    assert "```" not in text
    assert "\n### injected" not in text


def test_trajectory_groups_setup_and_equivalent_retries_without_hiding_failures() -> None:
    steps = (
        step("model.list", args={}, result={"models": [{"model": "ieee39"}]}, sequence=1),
        step(
            "context.open",
            args={"model": "ieee39"},
            result={"model": "ieee39", "counts": {"buses": 39, "lines": 35, "transformers": 11}},
            sequence=2,
        ),
        step(
            "model.dataset.query",
            args={"dataset": "result.res_line", "fields": ["bad_field"]},
            result={"code": "unknown_field", "message": "bad_field is not published"},
            ok=False,
            sequence=3,
        ),
        step(
            "model.dataset.query",
            args={"dataset": "result.res_line", "fields": ["loading_percent"], "limit": 5},
            result={"rows": [{"line": 17, "loading_percent": 132.51}], "row_count": 5},
            sequence=4,
        ),
    )
    text = "\n".join(render_analysis_trajectory(steps))
    assert text.count("准备 IEEE-39 仿真环境") == 1
    assert "2 次调用" in text
    assert "bad_field is not published" in text
    assert "改用 loading_percent" in text
    assert "线路 17：132.51%" in text


def test_density_target_compacts_low_information_steps_but_keeps_important_ones() -> None:
    steps = tuple(
        step(
            "model.dataset.describe",
            args={"dataset": f"dataset-{index}"},
            result={"field_count": index + 1},
            sequence=index,
        )
        for index in range(1, 9)
    ) + (
        step(
            "analysis.powerflow.ac.run",
            args={"operation": "powerflow.ac"},
            result={"converged": False, "message": "Newton-Raphson did not converge"},
            ok=False,
            sequence=20,
        ),
    )
    lines = render_analysis_trajectory(steps)
    text = "\n".join(lines)
    assert sum(line[:1].isdigit() for line in lines) <= 6
    assert "其余 3 次数据集结构核对" in text
    assert "Newton-Raphson did not converge" in text


def test_trajectory_attaches_recorded_decision_to_supporting_step() -> None:
    ranked = step(
        "result.branches.rank",
        args={"metric": "loading_percent", "limit": 5},
        result={"rows": [{"line": 17, "loading_percent": 132.51}]},
        sequence=4,
    )
    decision = TraceDecision(
        turn_id=ranked.turn_id,
        tool_call_id=ranked.tool_call_id,
        intent="识别过载线路",
        decision="线路 17 超过模型约束 100%",
        next_action="对线路 17 开展 N-1 校核",
    )
    text = "\n".join(render_analysis_trajectory((ranked,), decisions=(decision,)))
    assert "决策：线路 17 超过模型约束 100%；下一步：对线路 17 开展 N-1 校核" in text


def test_trajectory_does_not_attach_decision_by_turn_when_call_is_unmatched() -> None:
    powerflow = step(
        "analysis.powerflow.ac.run",
        args={"operation": "powerflow.ac"},
        result={"converged": True},
        sequence=1,
    )
    decision = TraceDecision(
        turn_id=powerflow.turn_id,
        tool_call_id="grid-record-decision-call",
        intent="说明下一步",
        decision="不应挂到潮流步骤",
        next_action="继续",
    )

    text = "\n".join(render_analysis_trajectory((powerflow,), decisions=(decision,)))

    assert "不应挂到潮流步骤" not in text
    assert "决策：" not in text


def test_trajectory_attaches_decision_by_explicit_support_ref() -> None:
    supported = step(
        "analysis.powerflow.ac.run",
        args={"operation": "powerflow.ac"},
        result={"converged": True, "result_ref": "result:sha256:" + "a" * 64},
        sequence=1,
    )
    decision = TraceDecision(
        turn_id=supported.turn_id,
        tool_call_id="grid-record-decision-call",
        intent="判断潮流结果",
        decision="潮流结果可作为后续排序依据",
        next_action="查询支路负载率",
        support_refs=("result:sha256:" + "a" * 64,),
    )

    text = "\n".join(render_analysis_trajectory((supported,), decisions=(decision,)))

    assert "决策：潮流结果可作为后续排序依据；下一步：查询支路负载率" in text


def test_trajectory_targets_support_ref_before_native_decision_tool_scope() -> None:
    supported_ref = "result:sha256:" + "a" * 64
    powerflow = step(
        "analysis.powerflow.ac.run",
        args={"operation": "powerflow.ac"},
        result={"converged": True, "result_ref": supported_ref},
        sequence=1,
    )
    decision_tool = step(
        "grid_record_decision",
        args={"intent": "判断潮流结果"},
        result={
            "intent": "判断潮流结果",
            "decision": "潮流结果支持后续排序",
            "next_action": "查询支路负载率",
            "refs": {"consumed": [supported_ref]},
        },
        sequence=2,
    )
    decision = TraceDecision(
        turn_id=powerflow.turn_id,
        tool_call_id=decision_tool.tool_call_id,
        intent="判断潮流结果",
        decision="潮流结果支持后续排序",
        next_action="查询支路负载率",
        support_refs=(supported_ref,),
    )

    lines = render_analysis_trajectory((powerflow, decision_tool), decisions=(decision,))
    text = "\n".join(lines)

    assert "决策：潮流结果支持后续排序；下一步：查询支路负载率" in text
    decision_at = text.index("决策：潮流结果支持后续排序")
    assert text.rindex("运行交流潮流计算", 0, decision_at) >= 0
    assert "grid_record_decision" not in text[:decision_at]


def test_trajectory_keeps_multiple_decisions_for_same_support_in_event_order() -> None:
    ranked = step(
        "result.branches.rank",
        args={"metric": "loading_percent", "limit": 5},
        result={"rows": [{"line": 17, "loading_percent": 132.51}]},
        sequence=1,
    )
    first = TraceDecision(
        turn_id=ranked.turn_id,
        tool_call_id=ranked.tool_call_id,
        intent="识别过载线路",
        decision="线路 17 超过 100%",
        next_action="检查约束来源",
    )
    second = TraceDecision(
        turn_id=ranked.turn_id,
        tool_call_id=ranked.tool_call_id,
        intent="确认后续校核",
        decision="线路 17 是首要 N-1 对象",
        next_action="执行单支路停运校核",
    )

    text = "\n".join(render_analysis_trajectory((ranked,), decisions=(first, second)))

    assert (
        "决策：线路 17 超过 100%；下一步：检查约束来源；"
        "线路 17 是首要 N-1 对象；下一步：执行单支路停运校核"
    ) in text
    assert text.index("线路 17 超过 100%") < text.index("线路 17 是首要 N-1 对象")


def test_trajectory_keeps_semantically_different_queries_separate_and_visible() -> None:
    steps = (
        step(
            "model.dataset.query",
            args={"dataset": "network.branches", "filters": {"line": 1}},
            result={"row_count": 1},
            sequence=1,
        ),
        step(
            "model.dataset.query",
            args={"dataset": "network.branches", "filters": {"line": 2}},
            result={"row_count": 1},
            sequence=2,
        ),
    )

    text = "\n".join(render_analysis_trajectory(steps))

    assert "等价调用" not in text
    assert text.count("查询 `network.branches`") == 2
    assert "filters=line=1" in text
    assert "filters=line=2" in text


def test_trajectory_keeps_identical_queries_with_different_key_results_separate() -> None:
    steps = (
        step(
            "model.dataset.query",
            args={"dataset": "result.res_line", "fields": ["line", "loading_percent"], "limit": 1},
            result={"rows": [{"line": 17, "loading_percent": 132.51}], "row_count": 1},
            sequence=1,
        ),
        step(
            "model.dataset.query",
            args={"dataset": "result.res_line", "fields": ["line", "loading_percent"], "limit": 1},
            result={"rows": [{"line": 22, "loading_percent": 91.25}], "row_count": 1},
            sequence=2,
        ),
    )

    text = "\n".join(render_analysis_trajectory(steps))

    assert "等价调用" not in text
    assert text.count("查询 `result.res_line`") == 2
    assert "线路 17：132.51%" in text
    assert "线路 22：91.25%" in text


def test_trajectory_renders_reuse_without_repeating_original_calculation() -> None:
    lines = render_analysis_trajectory(
        (),
        reuse_notes=("第 5 题交流潮流结果，未重复计算",),
    )
    assert lines == ["- 复用：第 5 题交流潮流结果，未重复计算"]
