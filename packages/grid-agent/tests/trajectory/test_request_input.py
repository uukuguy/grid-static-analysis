from grid_agent.trajectory.request_input import semantic_request_sha256


def test_semantic_digest_matches_javascript_without_rewriting_string_exponents() -> None:
    assert semantic_request_sha256({"actual": 1e-8, "text": "1e-08"}) == (
        "9fd094f7f06145a404c765f7ed350c5528d762bd3ab61481cc2e03e5545e0d99"
    )
