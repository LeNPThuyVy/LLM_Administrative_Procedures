import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

async def get_async_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[LLM SUMMARIZER] Warning: Chưa cấu hình OPENAI_API_KEY, sẽ dùng cắt chuỗi thô.")
        return None
    return AsyncOpenAI(api_key=api_key, timeout=30.0, max_retries=2)

async def summarize_text_with_llm(text: str) -> str:
    if not text.strip():
        return ""
        
    client = await get_async_client()
    if not client:
        return text[-3000:]
        
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    prompt = f"""Dưới đây là lịch sử trò chuyện cũ giữa User và Assistant. Hãy tóm tắt lại các điểm chính, ý định của User, và các thông tin đã được Assistant giải đáp trong khoảng tối đa 300 từ. Giữ lại các chi tiết quan trọng liên quan đến thủ tục.

LỊCH SỬ TRÒ CHUYỆN:
{text}
"""
    
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=400,
        )
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM SUMMARIZER] Lỗi khi tóm tắt: {e}")
        
    # Fallback to simple truncation if LLM fails
    return text[-3000:]
