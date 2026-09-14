"""
ui/evidence_panel.py

Hiển thị Evidence [1][2]... kèm snippet, dùng gr.Accordion để không chiếm
diện tích khi chưa cần xem chi tiết. Field khớp đúng API Evidence đã chốt
trong AI_CORE_CONTRACT.md: source_id, document_id, title, snippet, page_number.

Cách dùng trong app.py (Người 1):

    from ui.evidence_panel import build_evidence_accordion, update_evidence

    with gr.Blocks() as demo:
        ...
        evidence_accordion, evidence_markdown = build_evidence_accordion()
        ...
        # sau khi pipeline trả evidence_list:
        chat_btn.click(
            fn=handle_chat,          # hàm của Người 1, trả về evidence_list
            ...,
            outputs=[..., evidence_accordion, evidence_markdown],
        )

Trong handle_chat, cuối cùng return thêm:
    *update_evidence(evidence_list)
"""
import gradio as gr


def format_evidence_markdown(evidence_list: list[dict]) -> str:
    """
    evidence_list: list các dict theo API Evidence format:
        {"source_id": "1", "document_id": "...", "title": "...",
         "snippet": "...", "page_number": 4}  # page_number có thể thiếu/None

    Trả về 1 chuỗi Markdown để đổ vào gr.Markdown.
    """
    if not evidence_list:
        return "_Không có nguồn tham khảo cho câu trả lời này._"

    lines = ["### 📚 Nguồn tham khảo\n"]
    for ev in evidence_list:
        source_id = ev.get("source_id", "?")
        title = ev.get("title", "(không rõ tên tài liệu)")
        snippet = ev.get("snippet", "")
        page = ev.get("page_number")

        page_str = f" — trang {page}" if page else ""
        lines.append(f"**[{source_id}] {title}{page_str}**")
        lines.append(f"> {snippet}")
        lines.append("")  # dòng trống giữa các evidence

    return "\n".join(lines)


def build_evidence_accordion():
    """
    Tạo sẵn khung Accordion (ẩn khi chưa có evidence). Phải gọi hàm này
    BÊN TRONG `with gr.Blocks():` của Người 1 để component được gắn đúng layout.

    Trả về (accordion, markdown_component) — dùng làm `outputs` cho event
    của Gradio, cập nhật qua update_evidence().
    """
    with gr.Accordion("📚 Nguồn tham khảo", open=False, visible=False) as accordion:
        evidence_markdown = gr.Markdown()
    return accordion, evidence_markdown


def update_evidence(evidence_list: list[dict]):
    """
    Gọi hàm này sau khi có evidence_list từ pipeline, return kết quả
    (2 giá trị) làm output cho accordion + markdown component ở trên.

        return *update_evidence(evidence_list)   # nếu đây là 2 output cuối
        # hoặc
        accordion_update, md_update = update_evidence(evidence_list)
    """
    if not evidence_list:
        return gr.update(visible=False), ""
    return gr.update(visible=True, open=True), format_evidence_markdown(evidence_list)
