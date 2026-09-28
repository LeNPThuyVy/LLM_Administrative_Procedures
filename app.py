"""
Gradio UI application.

This module exposes `create_app()` which returns a `gr.Blocks` instance.
It can be:
  - Mounted into FastAPI via `backend/main.py` (unified server), or
  - Launched standalone: `py -3.12 -m app`
"""

import gradio as gr

from rag.pipeline import answer_query
from ui.clarification_box import build_clarification_box, update_clarification
from ui.evidence_panel import build_evidence_accordion, update_evidence


def _extract_text(val: object) -> str:
    """Safely extract string text from string, list, or dict message content."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_extract_text(item) for item in val if item)
    if isinstance(val, dict):
        if "text" in val and isinstance(val["text"], str):
            return val["text"]
        if "content" in val:
            return _extract_text(val["content"])
        return " ".join(_extract_text(v) for v in val.values() if v)
    return str(val) if val is not None else ""


def user_submit(message: str, history: list[dict]):
    """
    Step 1: Immediately append user prompt to chatbot history and clear input box.
    Renders instantly on UI when user hits Enter or clicks Send.
    """
    if not message or not message.strip():
        return "", history or []

    history = history or []
    history.append({"role": "user", "content": message.strip()})
    return "", history


def bot_respond(history: list[dict]):
    """
    Step 2: Execute RAG pipeline in background and append assistant answer + evidence.
    """
    if not history:
        return history, gr.update(visible=False), "", gr.update(visible=False), ""

    # Find the latest user query
    last_user_msg = ""
    for msg in reversed(history):
        if isinstance(msg, dict) and msg.get("role") == "user":
            last_user_msg = _extract_text(msg.get("content", ""))
            break
        elif isinstance(msg, (list, tuple)) and len(msg) >= 1:
            last_user_msg = _extract_text(msg[0])
            break

    if not last_user_msg or not last_user_msg.strip():
        return history, gr.update(visible=False), "", gr.update(visible=False), ""

    # Recent history (excluding current user prompt)
    recent_history = history[:-1]

    # Call AI Core RAG pipeline
    response = answer_query(
        query=last_user_msg,
        context={"recent_messages": recent_history}
    )

    # Determine displayed text and clarification state
    if response.needs_clarification:
        display_text = response.clarification_question or (
            "Bạn muốn hỏi về thủ tục hành chính nào? "
            "Vui lòng cung cấp thêm thông tin để tôi có thể hỗ trợ."
        )
        needs_clarification_flag = True
    else:
        display_text = response.answer or ""
        needs_clarification_flag = False

    # Append assistant response turn to history
    history.append({"role": "assistant", "content": display_text})

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

    acc_update, md_update = update_evidence(evidence_list)
    clar_box_update, clar_md_update = update_clarification(
        needs_clarification=needs_clarification_flag,
        question=display_text if needs_clarification_flag else "",
    )

    return (
        history,
        acc_update,
        md_update,
        clar_box_update,
        clar_md_update,
    )


def create_app() -> gr.Blocks:
    """
    Build and return the Gradio Blocks application.
    """

    with gr.Blocks(title="Trợ lý Thủ tục Hành chính AI") as demo:

        gr.Markdown("# Trợ lý Thủ tục Hành chính AI")

        gr.Markdown(
            "Hệ thống hỏi đáp thủ tục hành chính "
            "dựa trên mô hình RAG và dữ liệu pháp lý xác thực."
        )

        chatbot = gr.Chatbot(
            height=450,
        )

        # Clarification box
        clar_box, clar_md = build_clarification_box()

        # Evidence panel
        acc, acc_md = build_evidence_accordion()

        with gr.Row():
            msg_input = gr.Textbox(
                placeholder=(
                    "Nhập câu hỏi thủ tục hành chính "
                    "của bạn tại đây..."
                ),
                show_label=False,
                scale=8,
            )

            send_btn = gr.Button(
                "Gửi",
                variant="primary",
                scale=1,
            )

        # ============================================
        # INSTANT SUBMIT EVENT CHAINING
        # 1. user_submit: clears textbox & renders prompt in chatbot instantly without progress spinner
        # 2. bot_respond: runs RAG pipeline in background and appends answer
        # ============================================
        msg_input.submit(
            fn=user_submit,
            inputs=[msg_input, chatbot],
            outputs=[msg_input, chatbot],
            show_progress="hidden",
        ).then(
            fn=bot_respond,
            inputs=[chatbot],
            outputs=[
                chatbot,
                acc,
                acc_md,
                clar_box,
                clar_md,
            ],
            show_progress="hidden",
        )

        send_btn.click(
            fn=user_submit,
            inputs=[msg_input, chatbot],
            outputs=[msg_input, chatbot],
            show_progress="hidden",
        ).then(
            fn=bot_respond,
            inputs=[chatbot],
            outputs=[
                chatbot,
                acc,
                acc_md,
                clar_box,
                clar_md,
            ],
            show_progress="hidden",
        )

    return demo


if __name__ == "__main__":
    demo = create_app()
    demo.launch(server_name="127.0.0.1", server_port=7860)