"""
ui/clarification_box.py

Hiển thị UI riêng khi hệ thống cần hỏi lại user (needs_clarification = true) —
dùng màu/khung cảnh báo khác hẳn câu trả lời bình thường để user nhận ra ngay
đây không phải câu trả lời cuối cùng.

Cách dùng trong app.py (Người 1):

    from ui.clarification_box import build_clarification_box, update_clarification

    with gr.Blocks() as demo:
        ...
        clarification_box, clarification_markdown = build_clarification_box()
        ...

    # sau khi pipeline trả (answer_generator, evidence_list, needs_clarification):
    #   nếu needs_clarification=True, answer chính là câu hỏi làm rõ
    return *update_clarification(needs_clarification, question=answer)
"""
import gradio as gr


def format_clarification_markdown(question: str) -> str:
    return f"### ⚠️ Cần thêm thông tin\n\n{question}"


def build_clarification_box():
    """
    Khung cảnh báo màu vàng/cam (dùng elem_classes để style riêng qua CSS,
    xem ui/styles.py của phần polish Ngày 2). Ẩn mặc định.

    Trả về (box, markdown_component).
    """
    with gr.Group(visible=False, elem_classes=["clarification-box"]) as box:
        clarification_markdown = gr.Markdown()
    return box, clarification_markdown


def update_clarification(needs_clarification: bool, question: str = ""):
    """
    Gọi sau khi có kết quả needs_clarification từ pipeline.
    """
    if not needs_clarification:
        return gr.update(visible=False), ""
    return gr.update(visible=True), format_clarification_markdown(question)
