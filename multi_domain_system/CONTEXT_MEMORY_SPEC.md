# CONTEXT MEMORY SPEC

## 1. PostgreSQL Data Model

Context / Memory Manager sử dụng các bảng:

- sessions
- messages
- structured_context
- users (deprecated - Phase 1)
- conversation_summary (deprecated - Phase 1)
- long_term_memory (deprecated - Phase 1)

Evidence của câu trả lời được lưu dạng JSONB trong bảng `messages`.

## 2. Context Object

`get_context(session_id, query)` trả về (với `conversation_summary` trả về `""` và `long_term_memory` trả về `{}` khi tắt theo Phase 1):

```json
{
  "session": {},
  "user": {},
  "conversation_summary": "",
  "recent_messages": [],
  "structured_context": {},
  "long_term_memory": {}
}

## 3. get_context()

Hàm:

```python
await get_context(
    session_id,
    query
)

await update_memory(
    session_id,
    query,
    final_result
)

