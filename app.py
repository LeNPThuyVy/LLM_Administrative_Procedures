import gradio as gr

from rag.pipeline import answer_query
from ui.clarification_box import build_clarification_box, update_clarification
from ui.evidence_panel import build_evidence_accordion, update_evidence


def respond(message: str, history: list[dict]):
    """
    Handle user query, execute RAG pipeline, and return updated chat & evidence components.
    Compatible with Gradio 6.x default messages format (dict with role/content keys).
    """
    if not message.strip():
        return "", history, gr.update(visible=False), "", gr.update(visible=False), ""

    # history is already in dict format; use directly as recent_messages for RAG pipeline
    history = history or []

    # Call AI Core RAG pipeline
    response = answer_query(
        query=message,
        context={"recent_messages": history}
    )

    # Append new user-bot turn to history
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": response.answer})

    # Prepare evidence list for UI Evidence Panel
    evidence_list = []
    seen_ids = set()

    for claim in response.claims:
        for cit in claim.citations:
            if cit.evidence_id not in seen_ids:
                seen_ids.add(cit.evidence_id)
                evidence_list.append(
                    {
                        "source_id": cit.evidence_id,
                        "document_id": cit.document_id,
                        "title": cit.title,
                        "snippet": f"Mã văn bản: {cit.document_id} ({cit.chunk_id})",
                        "page_number": None,
                    }
                )

    # Check clarification needs
    needs_clarification = (
        "Thông tin trong tài liệu được cung cấp chưa đủ" in response.answer
    )

    acc_update, md_update = update_evidence(evidence_list)
    clar_box_update, clar_md_update = update_clarification(
        needs_clarification=needs_clarification,
        question=response.answer if needs_clarification else "",
    )

    return (
        "",
        history,
        acc_update,
        md_update,
        clar_box_update,
        clar_md_update,
    )


def create_app():
    """
    Build Gradio UI application with Chat Interface, Clarification Box, and Evidence Panel.
    Compatible across Gradio versions.
    """
    with gr.Blocks(title="Trợ lý Thủ tục Hành chính AI") as demo:
        gr.Markdown("#Trợ lý Thủ tục Hành chính AI")
        gr.Markdown(
            "Hệ thống hỏi đáp thủ tục hành chính dựa trên mô hình RAG và dữ liệu pháp lý xác thực."
        )

        chatbot = gr.Chatbot(height=450)

        # Clarification box component
        clar_box, clar_md = build_clarification_box()

        # Evidence panel accordion component
        acc, acc_md = build_evidence_accordion()

        with gr.Row():
            msg_input = gr.Textbox(
                placeholder="Nhập câu hỏi thủ tục hành chính của bạn tại đây...",
                show_label=False,
                scale=8,
            )
            send_btn = gr.Button("Gửi", variant="primary", scale=1)

        # Event triggers
        submit_args = {
            "fn": respond,
            "inputs": [msg_input, chatbot],
            "outputs": [msg_input, chatbot, acc, acc_md, clar_box, clar_md],
        }

        msg_input.submit(**submit_args)
        send_btn.click(**submit_args)

    return demo


if __name__ == "__main__":
    app = create_app()
    app.launch()