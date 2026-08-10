from grid_agent.contracts import AnswerEnvelope, AttemptStatus, RunRequest


def test_answer_envelope_has_exact_public_shape() -> None:
    envelope = AnswerEnvelope(question_id="q-1", answer_output="ok")

    assert envelope.model_dump() == {"question_id": "q-1", "answer_output": "ok"}


def test_plain_question_gets_id() -> None:
    request = RunRequest.from_text("  run AC power flow  ")

    assert request.question_id.startswith("q-")
    assert request.question == "run AC power flow"
    assert AttemptStatus.EXECUTION_FAILED.value == "execution_failed"
