from rag.retrieval import build_search_query


def run_test():
    context = {
        "structured_context": {
            "intent": "hỏi thành phần hồ sơ",
            "procedure_name": "Đăng ký thường trú",
            "location": "TP.HCM",
            "method": "Trực tuyến",
            "documents": [
                "CCCD",
                "Giấy khai sinh"
            ],
            "fee": "20000 đồng",
            "processing_time": "7 ngày",
            "applicant_type": "Cá nhân",
        },
        "long_term_memory": {
            "procedure_name": "Đăng ký thường trú",
            "location": "TP.HCM",
        }
    }

    query = "Tôi cần chuẩn bị giấy tờ gì?"

    search_query = build_search_query(
        query=query,
        context=context
    )

    print("=" * 70)
    print("QUERY GỐC:")
    print(query)

    print()
    print("SEARCH QUERY SAU KHI THÊM CONTEXT:")
    print(search_query)

    print("=" * 70)

    expected_values = [
        "Đăng ký thường trú",
        "TP.HCM",
        "hỏi thành phần hồ sơ",
    ]

    errors = []

    for value in expected_values:
        if value not in search_query:
            errors.append(
                f"Thiếu context: {value}"
            )

    if errors:
        print("RETRIEVAL CONTEXT TEST FAILED")

        for error in errors:
            print("-", error)

    else:
        print("RETRIEVAL CONTEXT TEST PASSED")
        print(
            "Retrieval đã sử dụng Structured Context "
            "để mở rộng câu truy vấn."
        )

    print("=" * 70)


if __name__ == "__main__":
    run_test()