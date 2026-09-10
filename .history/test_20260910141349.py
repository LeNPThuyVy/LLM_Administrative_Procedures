from rag.pipeline import answer_query


def test_qwen_direct():
    """Test Qwen directly through generate_answer."""
    from rag.generator import generate_answer

    prompt = """
Bạn là trợ lý AI hỗ trợ thủ tục hành chính.

Hãy trả lời bằng tiếng Việt, ngắn gọn:

Người dân cần chuẩn bị những gì để đăng ký khai sinh?
"""

    answer = generate_answer(prompt)

    print("\n===== QWEN DIRECT TEST =====")
    print(answer)


def test_full_pipeline():
    """Test the complete RAG pipeline with the real Qwen model."""

    query = "Tôi cần những giấy tờ gì để đăng ký khai sinh?"

    response = answer_query(
        query=query,
        context=None,
    )

    print("\n===== FULL PIPELINE TEST =====")

    print("\n--- ANSWER ---")
    print(response.answer)

    print("\n--- VERIFIED CLAIMS ---")

    for index, claim in enumerate(response.claims, start=1):
        print(f"\nClaim {index}:")
        print(f"  Claim       : {claim.claim}")
        print(f"  Status      : {claim.status}")
        print(f"  Reason      : {claim.reason}")

        print("  Citations:")

        if not claim.citations:
            print("    None")
            continue

        for citation in claim.citations:
            print(f"    Evidence ID : {citation.evidence_id}")
            print(f"    Document ID : {citation.document_id}")
            print(f"    Chunk ID    : {citation.chunk_id}")
            print(f"    Title       : {citation.title}")
            print(f"    Source URL  : {citation.source_url}")


if __name__ == "__main__":
    # Test Qwen first.
    test_qwen_direct()

    # Then test the complete RAG pipeline.
    test_full_pipeline()