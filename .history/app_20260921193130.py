"""
Gradio UI application.

This module exposes `create_app()` which returns a `gr.Blocks` instance.
It can be:
  - Mounted into FastAPI via `backend/main.py` (unified server), or
  - Launched standalone: `python app.py`
"""

import gradio as gr

from rag.pipeline import answer_query
from ui.clarification_box import build_clarification_box, update_clarification
from ui.evidence_panel import build_evidence_accordion, update_evidence
from ui.auth_panel import build_auth_panel


def respond(message: str, history: list[dict]):
    """
    Handle user query, execute RAG pipeline, and return updated chat & evidence
    components.

    Compatible with Gradio 6.x default messages format (dict with role/content
    keys).
    """
    if not message.strip():
        return "", history, gr.update(visible=False), "", gr.update(visible=False), ""

    # history is already in dict format; use directly as recent_messages
    history = history or []

    # Call AI Core RAG pipeline
    response = answer_query(
        query=message,
        context={"recent_messages": history}
    )

    # --- Determine displayed text and clarification state ---
    if response.needs_clarification:
        # Show clarification question in chat and in clarification box
        display_text = response.clarification_question or (
            "Bạn muốn hỏi về thủ tục hành chính nào? "
            "Vui lòng cung cấp thêm thông tin để tôi có thể hỗ trợ."
        )
        needs_clarification_flag = True
    else:
        display_text = response.answer or ""
        needs_clarification_flag = False

    # Append new user-bot turn to history
    history.append({"role": "user", "content": message})
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
        "",
        history,
        acc_update,
        md_update,
        clar_box_update,
        clar_md_update,
    )


def login_user(email, password):
    if not email or not email.strip():
        return (
            "Vui lòng nhập email.",
            gr.update(visible=True),
            gr.update(visible=False),
        )

    if not password or not password.strip():
        return (
            "Vui lòng nhập mật khẩu.",
            gr.update(visible=True),
            gr.update(visible=False),
        )

    # Tài khoản demo tạm thời
    DEMO_EMAIL = "minh@gmail.com"
    DEMO_PASSWORD = "123456"

    if email.strip() != DEMO_EMAIL or password != DEMO_PASSWORD:
        return (
            "Email hoặc mật khẩu không đúng.",
            gr.update(visible=True),
            gr.update(visible=False),
        )

    return (
        " Đăng nhập thành công.",
        gr.update(visible=False),
        gr.update(visible=True),
    )


def register_user(name, email, password, confirm_password):
    """
    Validate giao diện đăng ký.
    Sau này sẽ gọi API backend.
    """

    if not name or not name.strip():
        return " Vui lòng nhập họ và tên."

    if not email or not email.strip():
        return " Vui lòng nhập email."

    if not password:
        return " Vui lòng nhập mật khẩu."

    if len(password) < 6:
        return " Mật khẩu phải có ít nhất 6 ký tự."

    if password != confirm_password:
        return " Hai mật khẩu không khớp."

    return " Thông tin hợp lệ. Backend đăng ký tài khoản đang được tích hợp."


def logout_user():
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        "",
        "",
    )


def create_app() -> gr.Blocks:
    """
    Build and return the Gradio Blocks application.

    Can be mounted into FastAPI:
        gr.mount_gradio_app(fastapi_app, create_app(), path="/")

    Or launched standalone:
        create_app().launch()
    """

    with gr.Blocks(title="Trợ lý Thủ tục Hành chính AI") as demo:

        # ============================================
        # AUTH UI
        # ============================================
        auth = build_auth_panel()

        # ============================================
        # MAIN APPLICATION
        # Ban đầu ẩn, login thành công mới hiện
        # ============================================
        with gr.Column(visible=False) as main_app:

            gr.Markdown("# Trợ lý Thủ tục Hành chính AI")
            logout_btn = gr.Button("Đăng xuất")

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

            submit_args = {
                "fn": respond,
                "inputs": [msg_input, chatbot],
                "outputs": [
                    msg_input,
                    chatbot,
                    acc,
                    acc_md,
                    clar_box,
                    clar_md,
                ],
            }

            msg_input.submit(**submit_args)
            send_btn.click(**submit_args)

        # ============================================
        # LOGIN EVENT
        # ============================================
        auth["login_btn"].click(
            fn=login_user,
            inputs=[
                auth["login_email"],
                auth["login_password"],
            ],
            outputs=[
                auth["login_message"],
                auth["container"],
                main_app,
            ],
        )

        logout_btn.click(
            fn=logout_user,
            outputs=[
                auth["container"],
                main_app,
                auth["login_email"],
                auth["login_password"],
            ],
        )

        # ============================================
        # REGISTER EVENT
        # ============================================
        auth["register_btn"].click(
            fn=register_user,
            inputs=[
                auth["register_name"],
                auth["register_email"],
                auth["register_password"],
                auth["register_confirm"],
            ],
            outputs=[
                auth["register_message"],
            ],
        )

    return demo


if __name__ == "__main__":
    # Standalone launch (no FastAPI, Gradio only).
    # For the unified FastAPI + Gradio server, run: python backend/main.py
    demo = create_app()
    demo.launch(server_name="0.0.0.0", server_port=7860)