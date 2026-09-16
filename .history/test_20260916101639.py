from rag.retrieval import RetrievedChunk
from rag.synthesizer import ConsolidatedQuery, synthesizer


def make_fake_generator(response: str):
    def fake_generator(prompt: str) -> str:
        return response

    return fake_generator


# ---------------------------------------------------------
# Test 1 — Clear query, no history
# ---------------------------------------------------------

query = "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"

fake_generator = make_fake_generator(
    """
    {
        "resolved_query": "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?",
        "original_query": "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?",
        "needs_clarification": false,
        "clarification_question": null
    }
    """
)

result = synthesizer(
    query=query,
    history={},
    procedure_hint=[],
    generator=fake_generator,
)

assert isinstance(result, ConsolidatedQuery)
assert result.needs_clarification is False
assert result.resolved_query == query
assert result.original_query == query
assert result.clarification_question is None


# ---------------------------------------------------------
# Test 2 — Multi-turn query
# ---------------------------------------------------------

history = {
    "recent_messages": [
        {
            "role": "user",
            "content": "Tôi muốn đăng ký hộ kinh doanh ở Bình Dương.",
        },
        {
            "role": "assistant",
            "content": "Bạn muốn biết thông tin gì?",
        },
    ],
    "conversation_summary": "",
}

query = "Giấy tờ."

fake_generator = make_fake_generator(
    """
    {
        "resolved_query": "Tôi cần biết giấy tờ để đăng ký hộ kinh doanh ở Bình Dương.",
        "original_query": "Giấy tờ.",
        "needs_clarification": false,
        "clarification_question": null
    }
    """
)

result = synthesizer(
    query=query,
    history=history,
    procedure_hint=[],
    generator=fake_generator,
)

assert isinstance(result, ConsolidatedQuery)
assert result.needs_clarification is False
assert "giấy tờ" in result.resolved_query
assert "đăng ký hộ kinh doanh" in result.resolved_query
assert "Bình Dương" in result.resolved_query
assert result.original_query == "Giấy tờ."
assert result.clarification_question is None


# ---------------------------------------------------------
# Test 3 — Missing context
# ---------------------------------------------------------

query = "Giấy tờ."

fake_generator = make_fake_generator(
    """
    {
        "resolved_query": "",
        "original_query": "Giấy tờ.",
        "needs_clarification": true,
        "clarification_question": "Bạn muốn hỏi giấy tờ của thủ tục nào?"
    }
    """
)

result = synthesizer(
    query=query,
    history={},
    procedure_hint=[],
    generator=fake_generator,
)

assert isinstance(result, ConsolidatedQuery)
assert result.needs_clarification is True
assert result.clarification_question is not None
assert isinstance(result.clarification_question, str)
assert result.original_query == "Giấy tờ."


print("All synthesizer tests passed.")