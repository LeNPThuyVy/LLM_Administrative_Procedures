from rag.generator import generate_answer
from rag.synthesizer import ConsolidatedQuery, synthesizer


def print_result(case_name: str, result: ConsolidatedQuery) -> None:
    """Print a readable synthesizer result."""
    print(f"\n{'=' * 60}")
    print(case_name)
    print(f"{'=' * 60}")
    print(f"Original query:         {result.original_query}")
    print(f"Resolved query:         {result.resolved_query}")
    print(f"Needs clarification:    {result.needs_clarification}")
    print(f"Clarification question: {result.clarification_question}")


def debug_generator(prompt: str) -> str:
    raw_output = generate_answer(prompt)

    print("\n" + "=" * 60)
    print("RAW LLM OUTPUT")
    print("=" * 60)
    print(raw_output)
    print("=" * 60)

    return raw_output


def run_case_1() -> None:
    """Case 1: Clear query without conversation history."""
    query = "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?"

    result = synthesizer(
        query=query,
        history={},
        procedure_hint=[],
        generator=debug_generator,
    )

    print_result("CASE 1 — Clear query", result)

    # Type invariants
    assert isinstance(result, ConsolidatedQuery)
    assert isinstance(result.resolved_query, str)
    assert isinstance(result.original_query, str)
    assert isinstance(result.needs_clarification, bool)

    # Query identity
    assert result.original_query == query

    # Clear query should not require clarification
    assert result.needs_clarification is False

    # The resolved query should not be empty.
    assert result.resolved_query.strip()

    print("CASE 1 PASS")


def run_case_2() -> None:
    """Case 2: Resolve context from a multi-turn conversation."""
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

    result = synthesizer(
        query=query,
        history=history,
        procedure_hint=[],
        generator=debug_generator,
    )

    print_result("CASE 2 — Multi-turn", result)

    # Type invariants
    assert isinstance(result, ConsolidatedQuery)
    assert isinstance(result.resolved_query, str)
    assert isinstance(result.original_query, str)
    assert isinstance(result.needs_clarification, bool)

    # Original query must remain unchanged.
    assert result.original_query == query

    # The context is sufficient.
    assert result.needs_clarification is False

    # Resolved query must contain the important conversation context.
    resolved_query_lower = result.resolved_query.lower()

    assert "đăng ký hộ kinh doanh" in resolved_query_lower
    assert "bình dương" in resolved_query_lower

    # Resolved query should not be empty.
    assert result.resolved_query.strip()

    print("CASE 2 PASS")


def run_case_3() -> None:
    """Case 3: Ambiguous query without enough context."""
    query = "Giấy tờ"

    result = synthesizer(
        query=query,
        history={},
        procedure_hint=[],
        generator=debug_generator,
    )

    print_result("CASE 3 — Missing context", result)

    # Type invariants
    assert isinstance(result, ConsolidatedQuery)
    assert isinstance(result.resolved_query, str)
    assert isinstance(result.original_query, str)
    assert isinstance(result.needs_clarification, bool)

    # Original query must remain unchanged.
    assert result.original_query == query

    # Without context, the synthesizer should request clarification.
    assert result.needs_clarification is True

    # A clarification question must be provided.
    assert result.clarification_question is not None
    assert isinstance(result.clarification_question, str)
    assert result.clarification_question.strip()

    # The question should ask which procedure the user means.
    clarification_lower = result.clarification_question.lower()

    procedure_keywords = [
        "thủ tục",
        "giấy tờ",
    ]

    assert any(
        keyword in clarification_lower
        for keyword in procedure_keywords
    )

    print("CASE 3 PASS")


def main() -> None:
    print("Running real-LLM synthesizer tests...")
    print("Generator: rag.generator.generate_answer")

    run_case_1()
    run_case_2()
    run_case_3()

    print(f"\n{'=' * 60}")
    print("ALL REAL-LLM SYNTHESIZER TESTS PASSED")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()