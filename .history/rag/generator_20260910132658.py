from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from my_config import (
    MODEL_NAME,
    MAX_NEW_TOKENS,
    TEMPERATURE,
    TOP_P,
)


_tokenizer = None
_model = None


def _load_model() -> tuple[Any, Any]:
    """
    Load tokenizer and model only once.
    """

    global _tokenizer, _model

    if _tokenizer is None or _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        
        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.float16,
        )

        _model.eval()

    return _tokenizer, _model

def generate_answer(prompt: str) -> str:
    """
    Generate an answer from the given prompt.
    """

    if not prompt.strip():
        return ""

    tokenizer, model = _load_model()

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    )

    with torch.no_grad():
        outputs = model.generate(
            inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            do_sample=TEMPERATURE > 0,
        )

    new_tokens = outputs[0][inputs.shape[-1]:]

    answer = tokenizer.decode(
        new_tokens,
        skip_special_tokens=True,
    )

    return answer.strip()