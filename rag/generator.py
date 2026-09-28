from pathlib import Path
import subprocess
import my_config

def _parse_answer(stdout: str, prompt: str) -> str:
    """
    Extract the generated answer from llama-cli stdout.
    """
    if not stdout:
        return ""

    text = stdout.strip()

    if "[ Prompt:" in text:
        text = text.split("[ Prompt:", 1)[0].rstrip()

    # llama-cli có thể tự động cắt bớt prompt khi hiển thị ra màn hình bằng "... (truncated)"
    idx_truncated = text.rfind("... (truncated)")
    if idx_truncated != -1:
        # Câu trả lời nằm sau dấu xuống dòng của chuỗi này
        idx_nl = text.find("\n", idx_truncated)
        if idx_nl != -1:
            return text[idx_nl:].strip()
        return text[idx_truncated + len("... (truncated)"):].strip()

    # Nếu không bị truncate, nó có thể in toàn bộ prompt
    # 1. Prompt của synthesizer kết thúc sau "GỢI Ý THỦ TỤC/CHỦ ĐỀ:"
    # 2. Prompt của RAG kết thúc bằng "...tuân thủ nghiêm ngặt tất cả các quy tắc trên."
    idx_rag = text.rfind("tuân thủ nghiêm ngặt tất cả các quy tắc trên.")
    if idx_rag != -1:
        return text[idx_rag + len("tuân thủ nghiêm ngặt tất cả các quy tắc trên."):].strip()
        
    idx_syn = text.rfind("GỢI Ý THỦ TỤC/CHỦ ĐỀ:")
    if idx_syn != -1:
        idx_json_start = text.find("{", idx_syn)
        if idx_json_start != -1:
            return text[idx_json_start:].strip()

    # Fallback an toàn (nếu không có gì ở trên khớp)
    idx_prompt_start = text.find("\n> ")
    if idx_prompt_start != -1:
        text_after_prompt = text[idx_prompt_start + 3:]
        if "{" in text_after_prompt and "}" in text_after_prompt:
            return text_after_prompt[text_after_prompt.find("{"):].strip()
            
    return text.strip()

def generate_answer(
    prompt: str,
    model_path: Path | None = None
) -> str:
    """
    Generate an answer using local Qwen GGUF model through llama.cpp.
    If model_path is None, defaults to my_config.MODEL_3B_PATH.
    """

    if not prompt or not prompt.strip():
        return ""

    if model_path is None:
        model_path = getattr(my_config, "MODEL_3B_PATH", my_config.MODEL_PATH)

    if not model_path.exists():
        raise FileNotFoundError(
            f"GGUF model not found: {model_path}"
        )

    command = [
        "llama-cli",
        "-m", str(model_path),
        "-p", prompt,
        "-n", str(my_config.MAX_NEW_TOKENS),
        "--temp", str(my_config.TEMPERATURE),
        "--top-p", str(my_config.TOP_P),

        "--no-warmup",
        "-ngl", "0",
        "-c", "2048",

        "--single-turn",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    print("RAW STDOUT:", repr(result.stdout))

    if result.returncode != 0:
        raise RuntimeError(
            "llama-cli failed:\n"
            f"{result.stderr}"
        )

    answer = _parse_answer(result.stdout, prompt)

    if not answer:
        return (
            "Thông tin trong tài liệu được cung cấp "
            "chưa đủ để trả lời câu hỏi này."
        )

    return answer


def generate_answer_1_5b(prompt: str) -> str:
    """Helper for pre-retrieval Synthesizer agent using 1.5B model."""
    return generate_answer(prompt, model_path=my_config.MODEL_1_5B_PATH)


def generate_answer_3b(prompt: str) -> str:
    """Helper for post-RAG final answer generation using 3B model."""
    return generate_answer(prompt, model_path=my_config.MODEL_3B_PATH)