from __future__ import annotations


def test_non_convergence_is_not_marked_retryable(grid, context_ref: str) -> None:
    grid.engine.force_non_convergence = True

    error = grid.call_error("analysis.powerflow.ac.run", {"context_ref": context_ref})

    assert error.code == "powerflow_non_converged"
    assert error.retryable is False
    assert error.allowed_recovery_actions == (
        "inspect_network_diagnostics",
        "change_solver_profile",
        "report_non_convergence",
    )
    assert error.evidence_refs
