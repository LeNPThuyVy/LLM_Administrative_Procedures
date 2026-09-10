"""
test_app_standalone.py — CHỈ để Người 3 tự test 2 module UI trước khi
Người 1 có app.py thật. Không phải file nộp cuối cùng (app.py thật do
Người 1 phụ trách theo khung thư mục chung).

Mock lại đúng chữ ký hàm answer_query() mà Người 2 sẽ viết trong
rag/pipeline.py, để khi ghép thật chỉ cần đổi import.

Chạy: python test_app_standalone.py
"""
import time
import gradio as gr

from ui.evidence_panel import build_evidence_accordion, update_evidence
from ui.clarification_box import build_clarification_box, update_clarification


# ---- MOCK pipeline — sẽ thay bằng `from rag.pipeline import answer_query` ----
def mock_answer_query(query: str, context: dict):
    """
    Mô phỏng đúng chữ ký: answer_query(query, context)
        -> (answer_generator, evidence_list, needs_clarification)
    """
    if len(query.split()) < 3:
        needs_clarification = True
        question = "Bạn có thể nói rõ hơn bạn cần hỗ trợ thủ tục gì và ở tỉnh/thành nào không?"

        def gen():
            yield question

        return gen(), [], needs_clarification

    answer_text = (
        "Bạn cần chuẩn bị: 1) Giấy đề nghị đăng ký hộ kinh doanh [1], "
        "2) Bản sao CCCD [1], 3) Hợp đồng thuê địa điểm kinh doanh [2]."
    )
    evidence_list = [
        {
            "source_id": "1",
            "document_id": "nd-01-2021",
            "title": "Nghị định 01/2021/NĐ-CP",
            "snippet": "Hồ sơ đăng ký hộ kinh doanh gồm giấy đề nghị, bản sao CCCD...",
            "page_number": 4,
        },
        {
            "source_id": "2",
            "document_id": "tt-02-2019",
            "title": "Thông tư 02/2019/TT-BKHĐT",
            "snippet": "Địa điểm kinh doanh phải có hợp đồng thuê hoặc giấy tờ chứng minh quyền sử dụng...",
            "page_number": None,
        },
    ]

    def gen():
        for word in answer_text.split(" "):
            time.sleep(0.03)
            yield word + " "

    return gen(), evidence_list, False


# ---- Gradio app ----
with gr.Blocks(title="Legal AI Assistant — Demo (test UI độc lập)") as demo:
    gr.Markdown("## Legal AI Assistant — test module Evidence / Clarification")

    chatbot = gr.Chatbot(label="Hội thoại")
    query_box = gr.Textbox(label="Câu hỏi", placeholder="Nhập câu hỏi thủ tục hành chính...")
    send_btn = gr.Button("Gửi", variant="primary")

    clarification_box, clarification_md = build_clarification_box()
    evidence_accordion, evidence_md = build_evidence_accordion()

    state_context = gr.State({})  # sẽ là structured_context thật khi ghép với Người 1

    def handle_chat(query, history, context):
        history = history or []
        answer_gen, evidence_list, needs_clarification = mock_answer_query(query, context)

        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": ""})

        full_answer = ""
        for chunk in answer_gen:
            full_answer += chunk
            history[-1]["content"] = full_answer
            yield (
                history,
                "",
                *update_clarification(needs_clarification, question=full_answer if needs_clarification else ""),
                *update_evidence([] if needs_clarification else evidence_list),
            )

    send_btn.click(
        fn=handle_chat,
        inputs=[query_box, chatbot, state_context],
        outputs=[chatbot, query_box, clarification_box, clarification_md, evidence_accordion, evidence_md],
    )
    query_box.submit(
        fn=handle_chat,
        inputs=[query_box, chatbot, state_context],
        outputs=[chatbot, query_box, clarification_box, clarification_md, evidence_accordion, evidence_md],
    )

if __name__ == "__main__":
    demo.launch()
