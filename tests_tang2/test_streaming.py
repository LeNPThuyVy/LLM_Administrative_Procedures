from rag.pipeline import answer_question_stream


def test_stream_api_emits_final_event():
    def fake_stream(prompt: str):
        yield "Xin "
        yield "chào"

    events = list(
        answer_question_stream(
            query="Xin chào",
            domain=None,
            stream_generator=fake_stream,
            synthesizer_generator=lambda prompt: """
            {
                "resolved_query": "Xin chào",
                "original_query": "Xin chào",
                "needs_clarification": false,
                "clarification_question": null
            }
            """,
        )
    )

    assert events
    assert events[-1]["type"] == "final"
    assert "response" in events[-1]