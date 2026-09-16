from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from my_config import (
    MODEL_NAME,
    MAX_NEW_TOKENS,
    TEMPERATURE,
    TOP_P,
    DEVICE,
)


_tokenizer = None
_model = None


def _load_model() -> tuple[Any, Any]:
    """
    Load tokenizer and model only once.
    """
    global _tokenizer, _model

    if _tokenizer is None or _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
        )

        dtype = torch.float16 if DEVICE == "cuda" else torch.float32

        _model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=dtype,
            trust_remote_code=True,
        )

        _model.to(DEVICE)
        _model.eval()

        if _tokenizer.pad_token_id is None:
            if _tokenizer.eos_token_id is not None:
                _tokenizer.pad_token = _tokenizer.eos_token

    return _tokenizer, _model


def generate_answer(prompt: str) -> str:
    """
    Generate answer from RAG prompt.
    """

    if not prompt or not prompt.strip():
        return ""

    tokenizer, model = _load_model()

    messages = [
        {
            "role": "system",
            "content": (
                "Bạn là trợ lý thủ tục hành chính. "
                "Chỉ sử dụng thông tin trong bằng chứng được cung cấp. "
                "Nếu bằng chứng có thông tin trực tiếp trả lời câu hỏi "
                "thì phải sử dụng thông tin đó để trả lời."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    # Tạo prompt text trước để tránh lỗi BatchEncoding/Tensor
    try:
        formatted_prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception:
        formatted_prompt = (
            "Bạn là trợ lý thủ tục hành chính.\n\n"
            + prompt
            + "\n\nTRẢ LỜI:"
        )

    # Tokenize theo cách chuẩn, luôn nhận BatchEncoding
    encoded = tokenizer(
        formatted_prompt,
        return_tensors="pt",
        padding=False,
        truncation=True,
    )

    input_ids = encoded["input_ids"].to(DEVICE)

    attention_mask = encoded.get("attention_mask")
    if attention_mask is not None:
        attention_mask = attention_mask.to(DEVICE)

    generation_kwargs = {
        "input_ids": input_ids,
        "max_new_tokens": MAX_NEW_TOKENS,
        "do_sample": TEMPERATURE > 0,
        "repetition_penalty": 1.05,
    }

    if attention_mask is not None:
        generation_kwargs["attention_mask"] = attention_mask

    if tokenizer.pad_token_id is not None:
        generation_kwargs["pad_token_id"] = tokenizer.pad_token_id

    if tokenizer.eos_token_id is not None:
        generation_kwargs["eos_token_id"] = tokenizer.eos_token_id

    if TEMPERATURE > 0:
        generation_kwargs["temperature"] = TEMPERATURE
        generation_kwargs["top_p"] = TOP_P

    with torch.no_grad():
        outputs = model.generate(
            **generation_kwargs
        )

    generated_tokens = outputs[0][input_ids.shape[-1]:]

    answer = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True,
    ).strip()

    if not answer:
        return (
            "Thông tin trong tài liệu được cung cấp "
            "chưa đủ để trả lời câu hỏi này."
        )

    return answer