# CONTEXT MEMORY SPEC

## 1. PostgreSQL Data Model

Context / Memory Manager sử dụng các bảng:

- users
- sessions
- messages
- structured_context
- conversation_summary
- long_term_memory

Evidence của câu trả lời được lưu dạng JSONB trong bảng `messages`.

## 2. Context Object

`get_context(session_id, query)` trả về:

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

