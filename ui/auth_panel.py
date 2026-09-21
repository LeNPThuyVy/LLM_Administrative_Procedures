import gradio as gr


def build_auth_panel():
    """
    Giao diện Đăng nhập / Đăng ký.
    Backend auth sẽ được nối vào sau.
    """

    with gr.Column(visible=True) as auth_container:
        gr.Markdown(
            """
            # 🔐 Đăng nhập hệ thống

            Đăng nhập để sử dụng **Trợ lý Thủ tục Hành chính AI**.
            """
        )

        with gr.Tabs():
            # =========================
            # ĐĂNG NHẬP
            # =========================
            with gr.Tab("Đăng nhập"):
                login_email = gr.Textbox(
                    label="Email",
                    placeholder="Nhập email của bạn..."
                )

                login_password = gr.Textbox(
                    label="Mật khẩu",
                    placeholder="Nhập mật khẩu...",
                    type="password"
                )

                login_btn = gr.Button(
                    "Đăng nhập",
                    variant="primary"
                )

                login_message = gr.Markdown("")

            # =========================
            # ĐĂNG KÝ
            # =========================
            with gr.Tab("Đăng ký"):
                register_name = gr.Textbox(
                    label="Họ và tên",
                    placeholder="Nhập họ và tên..."
                )

                register_email = gr.Textbox(
                    label="Email",
                    placeholder="Nhập email..."
                )

                register_password = gr.Textbox(
                    label="Mật khẩu",
                    placeholder="Nhập mật khẩu...",
                    type="password"
                )

                register_confirm = gr.Textbox(
                    label="Nhập lại mật khẩu",
                    placeholder="Nhập lại mật khẩu...",
                    type="password"
                )

                register_btn = gr.Button(
                    "Đăng ký",
                    variant="primary"
                )

                register_message = gr.Markdown("")

    return {
        "container": auth_container,

        "login_email": login_email,
        "login_password": login_password,
        "login_btn": login_btn,
        "login_message": login_message,

        "register_name": register_name,
        "register_email": register_email,
        "register_password": register_password,
        "register_confirm": register_confirm,
        "register_btn": register_btn,
        "register_message": register_message,
    }