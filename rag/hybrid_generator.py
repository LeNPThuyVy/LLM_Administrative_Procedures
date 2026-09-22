"""
Hybrid generator: try remote Qwen3-4B first, fall back to local Qwen2.5-0.5B.

Issue #6 fix: persist which model actually served each query into the
query result log (printed as a structured tag so it can be grepped
from test result logs).
"""

import requests

from rag.generator import generate_answer as generate_local
from rag.remote_generator import generate_remote

# Tracks the model used for the last generate_hybrid() call.
# Exposed for test code that wants to assert which path was taken.
last_model_used: str = "unknown"


def generate_hybrid(prompt: str) -> str:
    """
    Try remote Qwen3-4B first.
    Fall back to local Qwen2.5-0.5B if remote generation fails.

    Issue #6: logs the model that served the request with a
    [MODEL_USED] tag for easy log filtering.
    """
    global last_model_used

    if not prompt or not prompt.strip():
        last_model_used = "none"
        return ""

    try:
        answer = generate_remote(prompt)

        if answer:
            last_model_used = "remote/Qwen3-4B"
            print(f"[HybridGenerator] [MODEL_USED=remote/Qwen3-4B] Using remote Qwen3-4B")
            return answer

        print("[HybridGenerator] Remote returned empty answer")

    except (requests.RequestException, ConnectionError, ValueError) as exc:
        print(
            f"[HybridGenerator] Remote unavailable: {exc}"
        )

    last_model_used = "local/Qwen2.5-0.5B"
    print("[HybridGenerator] [MODEL_USED=local/Qwen2.5-0.5B] Falling back to local Qwen")
    return generate_local(prompt)