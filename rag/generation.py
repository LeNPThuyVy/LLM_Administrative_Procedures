import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def get_client():
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Chưa cấu hình OPENAI_API_KEY"
        )

    return OpenAI(
        api_key=api_key,
        timeout=30.0,
        max_retries=2
    )


def build_prompt(
    query,
    context,
    evidence_candidates
):
    evidence_blocks = []

    for index, evidence in enumerate(
        evidence_candidates,
        start=1
    ):
        title = evidence.metadata.get(
            "title",
            "Không có tiêu đề"
        )

        block = f"""
[{index}]
Tiêu đề: {title}
Nội dung:
{evidence.content}
"""

        evidence_blocks.append(block)

    evidence_text = "\n".join(
        evidence_blocks
    )

    recent_messages = context.get(
        "recent_messages",
        []
    )

    history_text = "\n".join(
        [
            f'{msg["role"]}: {msg["content"]}'
            for msg in recent_messages[-6:]
        ]
    )

    structured_context = context.get(
        "structured_context",
        {}
    )

    prompt = f"""
Bạn là trợ lý hỏi đáp thủ tục hành chính.

QUY TẮC BẮT BUỘC:
1. Chỉ trả lời dựa trên EVIDENCE.
2. Không tự bịa thông tin.
3. Khi dùng nguồn nào phải ghi citation [1], [2], [3].
4. Không tạo citation không tồn tại.
5. Nếu dữ liệu không đủ thì nói rõ dữ liệu hiện có chưa đủ.
6. Trả lời bằng tiếng Việt.
7. Trình bày ngắn gọn, dễ hiểu.

STRUCTURED CONTEXT:
{structured_context}

HỘI THOẠI GẦN ĐÂY:
{history_text}

EVIDENCE:
{evidence_text}

CÂU HỎI:
{query}

TRẢ LỜI:
"""

    return prompt


def generate_answer_stream(
    query,
    context,
    evidence_candidates
):
    client = get_client()

    prompt = build_prompt(
        query,
        context,
        evidence_candidates
    )

    model = os.getenv(
        "OPENAI_MODEL",
        "gpt-4o-mini"
    )

    stream = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,
        stream=True
    )

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta.content

        if delta:
            yield delta