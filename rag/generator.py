"""
generator.py — LLM generation via llama-server HTTP endpoint.

GĐ1 mục 4: Chuyển từ llama-cli sang llama-server (HTTP daemon, nạp model một lần).
Giai đoạn 0: Xóa fallback subprocess, báo lỗi thân thiện khi server không chạy.
"""

import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import my_config

_SERVER_HOST = "http://127.0.0.1"
_SERVER_PORT_3B = 8080    # cổng cho model 3B (main RAG)
_SERVER_PORT_1_5B = 8081  # cổng cho model 1.5B (synthesizer)
_REQUEST_TIMEOUT = 120    # giây

_CHAT_PATH = "/v1/chat/completions"

class LLMUnavailableError(RuntimeError):
    pass

def _generate_via_server(prompt: str, port: int) -> str | None:
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

def generate_answer(
    prompt: str,
    model_path: Path | None = None,
    server_port: int = _SERVER_PORT_3B,
) -> str:
    if not prompt or not prompt.strip():
        return ""

    answer = _generate_via_server(prompt, server_port)
    if answer is not None:
        return answer if answer else (
            "Thông tin trong tài liệu được cung cấp "
            "chưa đủ để trả lời câu hỏi này."
        )

    raise LLMUnavailableError(f"llama-server at port {server_port} is not available.")


def generate_answer_1_5b(prompt: str) -> str:
    return generate_answer(
        prompt,
        server_port=_SERVER_PORT_1_5B,
    )


def generate_answer_3b(prompt: str) -> str:
    return generate_answer(
        prompt,
        server_port=_SERVER_PORT_3B,
    )


def stream_generate_via_server(prompt: str, port: int):
    if not prompt or not prompt.strip():
        yield ""
        return

    url = f"{_SERVER_HOST}:{port}{_CHAT_PATH}"
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "repeat_penalty": 1.1,
        "max_tokens": my_config.MAX_NEW_TOKENS,
        "stream": True,
    }).encode("utf-8")

    req = Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            for line in resp:
                line = line.decode('utf-8').strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                        if content:
                            yield content
                    except (KeyError, json.JSONDecodeError):
                        continue
    except (URLError, OSError) as exc:
        raise LLMUnavailableError(f"llama-server at port {port} is not available: {exc}")


def stream_answer_3b(prompt: str):
    yield from stream_generate_via_server(prompt, _SERVER_PORT_3B)