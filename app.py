import gradio as gr


def chat(message, history):
    return f"Bạn vừa hỏi: {message}"


demo = gr.ChatInterface(
    fn=chat,
    title="Trợ lý thủ tục hành chính",
    description="Demo hệ thống hỏi đáp thủ tục hành chính."
)


if __name__ == "__main__":
    demo.launch()