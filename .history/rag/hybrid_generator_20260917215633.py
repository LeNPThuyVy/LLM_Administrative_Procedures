import requests

from rag.generator import generate_answer as generate_local
from rag.remote_generator import generate_remote


def generate_hybrid(prompt: str) -> str:
    """
    Try remote Qwen first.
    Fall back to local Qwen if remote generation fails.
    """

    if not prompt or not prompt.strip():
        return ""

    try:
        answer = generate_remote(prompt)

        if answer:
            print("[HybridGenerator] Using remote Qwen3-4B")
            return answer

        print("[HybridGenerator] Remote returned empty answer")

    except (requests.RequestException, ConnectionError, ValueError) as exc:
    print(
        f"[HybridGenerator] Remote unavailable: {exc}"
    )

    print("[HybridGenerator] Falling back to local Qwen")
    return generate_local(prompt)