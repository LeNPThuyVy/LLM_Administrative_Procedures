import requests

from my_config import VAST_URL


def generate_remote(prompt: str) -> str:
    """
    Generate answer using the remote Qwen API on Vast.ai.
    """

    if not prompt or not prompt.strip():
        return ""

    response = requests.post(
        f"{VAST_URL}/generate",
        json={
            "prompt": prompt,
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    return data.get("answer", "").strip()