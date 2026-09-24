from rag.prompt_builder import _format_context


def run_test():
    context = {
        "conversation_summary": (
            "Người dùng đang hỏi về thủ tục "
            "đăng ký thường trú tại TP.HCM."
        ),

        "recent_messages": [
            {
                "role": "user",
                "content": (
                    "Tôi muốn làm thủ tục "
                    "đăng ký thường trú."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Bạn muốn đăng ký thường trú "
                    "ở khu vực nào?"
                ),
            },
            {
                "role": "user",
                "content": "Tôi ở TP.HCM.",
            },
        ],

        "structured_context": {
            "intent": "hỏi thành phần hồ sơ",
            "procedure_name": "Đăng ký thường trú",
            "location": "TP.HCM",
            "method": "Trực tuyến",
            "documents": [
                "CCCD",
                "Giấy khai sinh",
            ],
            "fee": "20000 đồng",
            "processing_time": "7 ngày",
            "applicant_type": "Cá nhân",
        },

        "long_term_memory": {
            "intent": "hỏi thành phần hồ sơ",
            "procedure_name": "Đăng ký thường trú",
            "location": "TP.HCM",
            "method": "Trực tuyến",
            "documents": [
                "CCCD",
                "Giấy khai sinh",
            ],
            "fee": "20000 đồng",
            "processing_time": "7 ngày",
            "applicant_type": "Cá nhân",
        },
    }

    context_text = _format_context(context)

    print("=" * 70)
    print("PROMPT CONTEXT:")
    print()
    print(context_text)
    print("=" * 70)

    expected_values = [
        "TÓM TẮT HỘI THOẠI TRƯỚC",
        "TIN NHẮN GẦN ĐÂY",
        "STRUCTURED CONTEXT",
        "LONG-TERM MEMORY",
        "Đăng ký thường trú",
        "TP.HCM",
        "CCCD",
        "20000 đồng",
        "7 ngày",
    ]

    errors = []

    for value in expected_values:
        if value not in context_text:
            errors.append(
                f"Thiếu dữ liệu trong prompt: {value}"
            )

    if errors:
        print()
        print("PROMPT CONTEXT TEST FAILED")

        for error in errors:
            print("-", error)

    else:
        print()
        print("PROMPT CONTEXT TEST PASSED")
        print(
            "Prompt Builder đã nhận đủ "
            "conversation_summary, recent_messages, "
            "structured_context và long_term_memory."
        )

    print("=" * 70)


if __name__ == "__main__":
    run_test()