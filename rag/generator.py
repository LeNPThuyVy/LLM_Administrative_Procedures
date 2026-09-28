"""
generator.py — LLM generation via llama-server HTTP endpoint.

GĐ1 mục 4: Chuyển từ llama-cli (subprocess mỗi lần, reload model) sang
llama-server (HTTP daemon, nạp model một lần, ~10x nhanh hơn).

Cách dùng:
1. Khởi động llama-server trước khi chạy app:
       llama-server -m model/Qwen2.5-3B-Instruct-Q4_K_M.gguf --port 8080 --ctx-size 4096
2. App gọi generate_answer_3b() / generate_answer_1_5b() bình thường.

Nếu llama-server chưa chạy, tự động fallback sang llama-cli (subprocess)
để không break hệ thống hiện tại.
"""

import json
import subprocess
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import my_config


# =========================================================
# SERVER CONFIG
# =========================================================

_SERVER_HOST = "http://127.0.0.1"
_SERVER_PORT_3B = 8080    # cổng cho model 3B (main RAG)
_SERVER_PORT_1_5B = 8081  # cổng cho model 1.5B (synthesizer)
_REQUEST_TIMEOUT = 120    # giây

# llama-server chat endpoint
_CHAT_PATH = "/v1/chat/completions"


# =========================================================
# HTTP GENERATION (llama-server)
# =========================================================

def _generate_via_server(prompt: str, port: int) -> str | None:
    """
    Gọi llama-server tại localhost:{port}/v1/chat/completions.

    Trả về chuỗi answer, hoặc None nếu server không sẵn sàng.
    """
    if not prompt or not prompt.strip():
        return ""

    url = f"{_SERVER_HOST}:{port}{_CHAT_PATH}"
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "repeat_penalty": 1.1,
        "max_tokens": my_config.MAX_NEW_TOKENS,
        "stream": False,
    }).encode("utf-8")

    req = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (
                data["choices"][0]["message"]["content"]
                .strip()
            )
    except (URLError, OSError, KeyError, json.JSONDecodeError):
        return None


# =========================================================
# SUBPROCESS FALLBACK (llama-cli)
# =========================================================

def _parse_answer(stdout: str, prompt: str) -> str:
    """
    Extract the generated answer from llama-cli stdout.
    Kept for fallback compatibility.
    """
    if not stdout:
        return ""

    text = stdout.strip()

    if "[ Prompt:" in text:
        text = text.split("[ Prompt:", 1)[0].rstrip()

    idx_truncated = text.rfind("... (truncated)")
    if idx_truncated != -1:
        idx_nl = text.find("\n", idx_truncated)
        if idx_nl != -1:
            return text[idx_nl:].strip()
        return text[idx_truncated + len("... (truncated)"):].strip()

    idx_rag = text.rfind("tuân thủ nghiêm ngặt tất cả các quy tắc trên.")
    if idx_rag != -1:
        return text[idx_rag + len("tuân thủ nghiêm ngặt tất cả các quy tắc trên."):].strip()

    idx_syn = text.rfind("GỢI Ý THỦ TỤC/CHỦ ĐỀ:")
    if idx_syn != -1:
        idx_json_start = text.find("{", idx_syn)
        if idx_json_start != -1:
            return text[idx_json_start:].strip()

    return text.strip()


def _generate_via_subprocess(
    prompt: str,
    model_path: Path,
) -> str:
    """
    Fallback: gọi llama-cli qua subprocess.
    Chỉ dùng khi llama-server không sẵn sàng.
    """
    if not model_path.exists():
        raise FileNotFoundError(
            f"GGUF model not found: {model_path}"
        )

    command = [
        "llama-cli",
        "-m", str(model_path),
        "-p", prompt,
        "-n", str(my_config.MAX_NEW_TOKENS),
        "--temp", "0.3",
        "--top-p", str(my_config.TOP_P),
        "--repeat-penalty", "1.1",
        "--ctx-size", "4096",
        "--single-turn",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_REQUEST_TIMEOUT,
    )

    print("RAW STDOUT:", repr(result.stdout[:200]))

    if result.returncode != 0:
        raise RuntimeError(
            "llama-cli failed:\n"
            f"{result.stderr}"
        )

    return _parse_answer(result.stdout, prompt)


# =========================================================
# PUBLIC API
# =========================================================

def generate_answer(
    prompt: str,
    model_path: Path | None = None,
    server_port: int = _SERVER_PORT_3B,
) -> str:
    """
    Generate an answer using local Qwen GGUF model.

    Ưu tiên llama-server HTTP (nhanh, không reload model).
    Fallback sang llama-cli subprocess nếu server chưa chạy.

    Args:
        prompt: Prompt đầy đủ.
        model_path: Đường dẫn GGUF (chỉ dùng khi fallback subprocess).
        server_port: Port của llama-server daemon.
    """
    if not prompt or not prompt.strip():
        return ""

    # --- Try HTTP server first ---
    answer = _generate_via_server(prompt, server_port)
    if answer is not None:
        return answer if answer else (
            "Thông tin trong tài liệu được cung cấp "
            "chưa đủ để trả lời câu hỏi này."
        )

    # --- Fallback to subprocess ---
    print(
        f"[generator] llama-server port {server_port} not available, "
        "falling back to llama-cli subprocess"
    )
    if model_path is None:
        model_path = getattr(my_config, "MODEL_3B_PATH", my_config.MODEL_PATH)

    answer = _generate_via_subprocess(prompt, model_path)
    return answer if answer else (
        "Thông tin trong tài liệu được cung cấp "
        "chưa đủ để trả lời câu hỏi này."
    )


def generate_answer_1_5b(prompt: str) -> str:
    """Helper for pre-retrieval Synthesizer agent using 1.5B model."""
    return generate_answer(
        prompt,
        model_path=my_config.MODEL_1_5B_PATH,
        server_port=_SERVER_PORT_1_5B,
    )


def generate_answer_3b(prompt: str) -> str:
    """Helper for post-RAG final answer generation using 3B model."""
    return generate_answer(
        prompt,
        model_path=my_config.MODEL_3B_PATH,
        server_port=_SERVER_PORT_3B,
    )