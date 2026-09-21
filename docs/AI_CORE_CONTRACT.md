# AI CORE CONTRACT v1.0

> **Purpose:** Source of Truth cho Input / Output và responsibility giữa các module AI Core.
>
> **Scope:** Context / Memory → Retrieval / Reranking → Evidence Builder → RAG Context Assembly → LLM → Evidence Verification → Evidence Mapper.
>
> **Implementation rule:** Các module phải tuân thủ contract này. Những vấn đề chưa được chốt được ghi trong `Open Questions` và không tự ý thay đổi interface trong implementation.

---

# 1. Overall Data Flow

```text
User Query
    ↓
Context Manager
    ↓
Query Analysis / Multi-agent
    ↓
ConsolidatedQuery
    ↓
needs_clarification?
    ├── True
    │      ↓
    │  Clarification Response
    │
    └── False
           ↓
      resolved_query
           ↓
      Official Retrieval
           ↓
      Reranking
           ↓
      Evidence Builder
           ↓
      RAG Context Assembly
           ↓
      LLM Generation
           ↓
      Evidence Verification
           ↓
      Evidence Mapper
           ↓
      Final Answer
```

### Query Analysis / Multi-agent

Query Analysis được thực hiện trước Official Retrieval và gồm ba component:

1. `history_reader`
2. `procedure_reader`
3. `synthesizer`

Flow logic:

```text
ConsolidatedQuery
        ↓
needs_clarification?
    ├── True
    │      ↓
    │  Clarification Response
    │
    └── False
           ↓
      resolved_query
           ↓
      Official Retrieval
```

`needs_clarification` là **nhánh điều kiện**, không phải một bước mà mọi query đều phải đi qua.

`Planning` chưa được mô tả như một module bắt buộc trong Contract v1 vì implementation hiện tại chưa có module Planning riêng.

`procedure_reader` thực hiện một Retrieval nhẹ để cung cấp procedure/topic hint cho `synthesizer`. Retrieval này **không thay thế Official Retrieval**.

Official Retrieval vẫn được thực hiện sau khi `synthesizer` tạo `resolved_query`.


# 2. Core Concepts

## 2.1. Context

Context là thông tin được lấy từ conversation và memory để giúp AI hiểu trạng thái và nhu cầu của người dùng.

Context bao gồm:

```text
conversation_summary
recent_messages
structured_context
long_term_memory
```

Context **không phải** là legal evidence.

---

## 2.2. Retrieved Chunk

`RetrievedChunk` là một chunk của tài liệu pháp lý được Retrieval tìm thấy và xem là candidate liên quan đến query.

Retrieved Chunk có thể chứa:

- Điều khoản pháp luật
- Nội dung nghị định / thông tư
- Quy định
- Các đoạn nội dung pháp lý liên quan khác

Retrieved Chunk **chưa được xem là Evidence cuối cùng**.

---

## 2.3. Evidence Candidate

`EvidenceCandidate` là Retrieved Chunk được Evidence Builder chuẩn bị để phục vụ:

1. RAG Context Assembly.
2. Evidence Verification.

Evidence Candidate **chưa phải Verified Evidence**.

---

## 2.4. Verified Evidence

`VerifiedEvidence` là nguồn được Evidence Verification xác nhận có thể hỗ trợ một hoặc nhiều claim trong câu trả lời của LLM.

Flow:

```text
Retrieved Chunk
      ↓
Evidence Candidate
      ↓
Verified Evidence
```

---

---

## 2.5. Query Analysis — Multi-agent

Query Analysis là lớp xử lý query ở đầu AI Core, trước Official Retrieval.

Query Analysis sử dụng ba component:

1. `history_reader`
2. `procedure_reader`
3. `synthesizer`

### Responsibility

#### `history_reader`

`history_reader` chịu trách nhiệm:

- Đọc `recent_messages`.
- Đọc `conversation_summary`.
- Chuẩn bị history để `synthesizer` sử dụng.
- Không gọi LLM.
- Không thực hiện Retrieval.

#### `procedure_reader`

`procedure_reader` chịu trách nhiệm:

- Gọi Retrieval hiện có với `top_k` nhỏ để lấy procedure/topic hint.
- Cung cấp hint cho `synthesizer`.
- Không phải Official Retrieval.
- Không quyết định câu trả lời cuối cùng.

Trong implementation Day 1:

```text
procedure_reader
    ↓
retrieve(query, context, top_k=2)
    ↓
procedure/topic hint
```

Retrieval của `procedure_reader` là một Retrieval nhẹ phục vụ Query Analysis.

Official Retrieval vẫn chạy sau `synthesizer` bằng `resolved_query`.

#### `synthesizer`

`synthesizer` chịu trách nhiệm:

- Nhận current query.
- Nhận history đã được `history_reader` chuẩn bị.
- Nhận procedure/topic hint từ `procedure_reader`.
- Tạo `ConsolidatedQuery`.
- Quyết định query có đủ context hay cần clarification.
- Tạo `resolved_query` khi đủ context.
- Tạo `clarification_question` khi thiếu context.

`synthesizer` không chịu trách nhiệm:

- Trả lời câu hỏi pháp lý.
- Tạo Evidence.
- Official Retrieval.
- Reranking.
- Evidence Verification.
- Gọi MCP.

### Important Boundary

```text
procedure_reader
    ↓
procedure/topic hint
    ↓
synthesizer
    ↓
resolved_query
    ↓
Official Retrieval
```

Không được hiểu:

```text
procedure_reader = Official Retrieval
```

Một request bình thường có thể có hai Retrieval calls:

```text
1. procedure_reader → Retrieval nhẹ, top_k=2
2. Official Retrieval → Retrieval chính thức bằng resolved_query
```

Đây là behavior được thiết kế trong Day 1 và không phải lỗi duplicate Retrieval.

---

## 2.6. ConsolidatedQuery

`ConsolidatedQuery` là output trung gian của Query Analysis.

Schema:

```text
ConsolidatedQuery
    resolved_query: string
    original_query: string
    needs_clarification: boolean
    clarification_question: string | null
```

### Field Responsibility

| Field | Responsibility | Description |
|---|---|---|
| `resolved_query` | Synthesizer / LLM | Query đã được bổ sung context cần thiết để Official Retrieval sử dụng |
| `original_query` | Python / deterministic code | Query gốc do user cung cấp, được giữ nguyên từ biến `query` |
| `needs_clarification` | Synthesizer / LLM | Cho biết context hiện tại có đủ để xác định query hay không |
| `clarification_question` | Synthesizer / LLM | Câu hỏi làm rõ khi `needs_clarification = true`; ngược lại là `null` |

### Deterministic `original_query`

`original_query` không được xem là một field do LLM sinh ra.

Trong implementation:

```text
original_query = query
```

Code phải giữ nguyên giá trị của `query` khi gán `original_query`.

Không thực hiện preprocessing như:

```text
strip
lower
normalize
```

hoặc bất kỳ phép biến đổi nào khác trên `query` trước khi gán.

LLM không có quyền override giá trị `original_query`.

### `resolved_query`

`resolved_query` được tạo bởi `synthesizer` dựa trên:

```text
current query
+
conversation history
+
procedure/topic hint
```

Nếu history cung cấp đủ context cho một câu hỏi tham chiếu, context đó được bổ sung vào `resolved_query`.

Ví dụ:

```text
History:
User: "Tôi muốn đăng ký hộ kinh doanh ở Bình Dương."

Current query:
"Giấy tờ."
```

Có thể tạo:

```text
resolved_query:
"Tôi cần biết giấy tờ để đăng ký hộ kinh doanh ở Bình Dương."
```

### Clarification

Nếu thông tin hiện có không đủ để xác định thủ tục hoặc đối tượng mà user đang hỏi:

```text
needs_clarification = true
```

và:

```text
clarification_question != null
```

Trong trường hợp này không tự chọn một thủ tục hoặc thêm thông tin pháp lý chưa được cung cấp.

Nếu đủ context:

```text
needs_clarification = false
clarification_question = null
```

### Clarification Branch

Khi `needs_clarification = true`, pipeline trả về Clarification Response và không tiếp tục:

```text
Official Retrieval
Reranking
Evidence Builder
RAG Context Assembly
LLM final answer generation
Evidence Verification
Evidence Mapper
```

Khi `needs_clarification = false`, pipeline tiếp tục bằng:

```text
resolved_query
    ↓
Official Retrieval
```


# 3. Contract 1 — Context Manager

## 3.1. Responsibility

Context Manager chịu trách nhiệm:

- Lấy thông tin liên quan từ conversation.
- Lấy `conversation_summary`.
- Lấy `recent_messages`.
- Lấy `structured_context`.
- Lấy `long_term_memory` phù hợp.
- Tổng hợp thành Context Object.
- Cập nhật context/memory sau khi AI xử lý nếu cần.

Context Manager **không chịu trách nhiệm**:

- Embedding
- Vector Search
- Retrieval
- Reranking
- Evidence Building
- Evidence Verification
- LLM Generation

---

## 3.2. Input

```json
{
  "session_id": "session_001",
  "query": "Tôi muốn đăng ký hộ kinh doanh ở Ho Chi Minh."
}
```

### Required

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Định danh conversation/session |
| `query` | string | Query hiện tại của người dùng |

---

## 3.3. Output — Context Object

```json
{
  "session_id": "session_001",
  "query": "Tôi muốn đăng ký hộ kinh doanh ở Ho Chi Minh.",
  "conversation_summary": {
    "summary": "Người dùng đang tìm hiểu thủ tục đăng ký hộ kinh doanh."
  },
  "recent_messages": [
    {
      "role": "user",
      "content": "Tôi muốn đăng ký hộ kinh doanh."
    },
    {
      "role": "assistant",
      "content": "Bạn muốn đăng ký ở đâu?"
    }
  ],
  "structured_context": {
    "location": "Ho Chi Minh",
    "procedure": "Đăng ký hộ kinh doanh"
  },
  "long_term_memory": []
}
```

### Required

```text
session_id
query
conversation_summary
recent_messages
structured_context
long_term_memory
```

### Null / Empty Convention

Các collection không có dữ liệu sử dụng:

```json
[]
```

hoặc object rỗng:

```json
{}
```

thay vì `null`.

---

# 4. Context Schema

## 4.1. conversation_summary

```json
{
  "summary": "Người dùng đang tìm hiểu thủ tục đăng ký hộ kinh doanh."
}
```

Terminology thống nhất:

```text
conversation_summary
    └── summary
```

---

## 4.2. recent_messages

```json
[
  {
    "role": "user",
    "content": "Tôi muốn đăng ký hộ kinh doanh."
  },
  {
    "role": "assistant",
    "content": "Bạn muốn đăng ký ở đâu?"
  }
]
```

---

## 4.3. structured_context

Structured Context sử dụng dynamic object.

Ví dụ:

```json
{
  "location": "Ho Chi Minh",
  "procedure": "Đăng ký hộ kinh doanh"
}
```

Nguyên tắc:

- Có thể bổ sung field mới khi phát hiện thông tin mới.
- Không yêu cầu schema cố định cho mọi conversation.
- Chỉ lưu thông tin được xác định từ conversation.
- Không tự suy diễn thông tin người dùng chưa cung cấp.

---

## 4.4. long_term_memory

Long-term Memory chứa thông tin có giá trị cho các conversation sau.

Ví dụ:

```json
[
  {
    "memory_id": "M001",
    "memory_type": "preference",
    "content": "User thường quan tâm đến thủ tục hành chính.",
    "importance": 0.8
  }
]
```

Trong PoC đầu tiên:

- Chưa triển khai semantic/vector retrieval riêng cho memory.
- Tập trung vào persistent memory cơ bản.

---

# 5. Contract 2 — Retrieval

## 5.1. Responsibility

Retrieval chịu trách nhiệm:

- Nhận query và context.
- Query processing.
- Embedding.
- Vector Search.
- Trả về các Retrieved Chunks liên quan.
- Giữ thông tin cần thiết cho traceability.

Retrieval **không chịu trách nhiệm**:

- Xác định Verified Evidence.
- Evidence Verification.
- Sinh câu trả lời.
- Quyết định claim nào của LLM là đúng.

---

## 5.2. Input

```json
{
  "query": "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?",
  "context": {
    "conversation_summary": {
      "summary": "Người dùng đang tìm hiểu thủ tục đăng ký hộ kinh doanh."
    },
    "recent_messages": [],
    "structured_context": {
      "location": "Ho Chi Minh",
      "procedure": "Đăng ký hộ kinh doanh"
    },
    "long_term_memory": []
  }
}
```

### Required

| Field | Type | Description |
|---|---|---|
| `query` | string | Query cần tìm kiếm |
| `context` | Context Object | Context được Context Manager xây dựng |

---

# 6. Retrieved Chunk Contract

## 6.1. Output

```json
{
  "results": [
    {
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "retrieval_score": 0.92,
      "metadata": {
        "title": "Đăng ký hộ kinh doanh",
        "document_type": "Nghị định",
        "page_number": 4
      }
    }
  ]
}
```

---

## 6.2. Required Fields

| Field | Type | Description |
|---|---|---|
| `chunk_id` | string | ID duy nhất của chunk |
| `document_id` | string | ID của tài liệu chứa chunk |
| `content` | string | Nội dung chunk |
| `retrieval_score` | float | Điểm relevance/similarity từ Retrieval |

---

## 6.3. metadata

`metadata` là object mở để chứa thông tin bổ sung cần thiết cho downstream modules.

Có thể bao gồm:

```text
title
document_type
page_number
article
clause
source_url
...
```

Metadata cụ thể có thể được mở rộng khi implementation xác định được yêu cầu thực tế.

---

# 7. Contract 3 — Reranking

## 7.1. Responsibility

Reranking đánh giá lại mức độ liên quan của Retrieved Chunks và sắp xếp chúng theo `rerank_score`.

Không tạo model `RerankedChunk` riêng.

Một Retrieved Chunk sau Reranking vẫn là Retrieved Chunk và được bổ sung:

```text
rerank_score
```

---

## 7.2. Output

```json
{
  "results": [
    {
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "retrieval_score": 0.92,
      "rerank_score": 0.95,
      "metadata": {
        "title": "Đăng ký hộ kinh doanh",
        "document_type": "Nghị định",
        "page_number": 4
      }
    }
  ]
}
```

### Score Semantics

```text
retrieval_score
→ mức độ liên quan từ Retrieval

rerank_score
→ mức độ liên quan sau Reranking
```

Hai score **không đại diện cho độ tin cậy pháp lý**.

---

## 7.3. Reranking Algorithm

Chưa freeze thuật toán/model Reranking trong Contract v1.

Implementation/evaluation sẽ quyết định:

- Reranker model.
- Cách tính score.
- Số lượng chunk giữ lại sau Reranking.
- Benchmark giữa các phương án.

---

# 8. Contract 4 — Evidence Builder

## 8.1. Responsibility

Evidence Builder là helper/preparation layer cho Evidence Verification.

Nhiệm vụ:

- Nhận Retrieved Chunks đã qua Reranking.
- Chuẩn bị candidate evidence.
- Normalize / enrich metadata nếu cần.
- Giữ traceability.
- Giảm phạm vi dữ liệu Verification cần đối chiếu.
- Chuẩn bị context phù hợp cho RAG.

Evidence Builder **không**:

- Thực hiện Retrieval lại.
- Xác định Verified Evidence cuối cùng.
- Kết luận claim của LLM là đúng/sai.

---

## 8.2. Input

```json
{
  "results": [
    {
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "retrieval_score": 0.92,
      "rerank_score": 0.95,
      "metadata": {
        "title": "Đăng ký hộ kinh doanh",
        "document_type": "Nghị định",
        "page_number": 4
      }
    }
  ]
}
```

---

## 8.3. Output — Evidence Candidates

```json
{
  "evidence_candidates": [
    {
      "candidate_id": "EC001",
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "title": "Đăng ký hộ kinh doanh",
      "document_type": "Nghị định",
      "page": 4,
      "source_url": "...",
      "retrieval_score": 0.92,
      "rerank_score": 0.95
    }
  ]
}
```

### Important

`EvidenceCandidate` chưa phải Evidence cuối cùng.

Không gán:

```text
verification_status = supported
```

ở bước Evidence Builder.

---

# 9. Contract 5 — RAG Context Assembly

## 9.1. Responsibility

RAG Context Assembly tổng hợp dữ liệu cần thiết để cung cấp cho LLM.

Input gồm:

```text
Query
+
Context
+
Evidence Candidates
```

---

## 9.2. Input

```json
{
  "query": "Tôi cần giấy tờ gì để đăng ký hộ kinh doanh?",
  "context": {
    "conversation_summary": {
      "summary": "Người dùng đang tìm hiểu thủ tục đăng ký hộ kinh doanh."
    },
    "recent_messages": [],
    "structured_context": {
      "location": "Ho Chi Minh",
      "procedure": "Đăng ký hộ kinh doanh"
    },
    "long_term_memory": []
  },
  "evidence_candidates": [
    {
      "candidate_id": "EC001",
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "rerank_score": 0.95
    }
  ]
}
```

---

# 10. Contract 6 — LLM Generation

## 10.1. Input

LLM nhận:

```text
Query
+
Context
+
RAG Context
```

---

## 10.2. Output

```json
{
  "answer": "Để đăng ký hộ kinh doanh, bạn cần chuẩn bị..."
}
```

LLM không tự xác nhận Evidence cuối cùng.

Evidence cuối cùng được xác định bởi Evidence Verification sau khi có answer.

---

# 11. Contract 7 — Evidence Verification

## 11.1. Responsibility

Evidence Verification đóng vai trò là lớp kiểm chứng sau LLM.

Nhiệm vụ:

- Nhận answer từ LLM.
- Đối chiếu answer với Evidence Candidates.
- Xác định Evidence có hỗ trợ claim hay không.
- Phân loại trạng thái verification.
- Tạo Verified Evidence.
- Phát hiện các claim không có Evidence hỗ trợ.

Verification **không cần Retrieval lại toàn bộ knowledge base trong flow chính**.

---

## 11.2. Input

```json
{
  "answer": "Để đăng ký hộ kinh doanh, bạn cần chuẩn bị...",
  "evidence_candidates": [
    {
      "candidate_id": "EC001",
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "rerank_score": 0.95
    }
  ]
}
```

---

## 11.3. Verification Status

```text
supported
partial
unsupported
pending
```

### Meaning

- `supported`: Evidence hỗ trợ claim.
- `partial`: Evidence chỉ hỗ trợ một phần claim.
- `unsupported`: Không tìm thấy Evidence phù hợp để hỗ trợ claim.
- `pending`: Chưa thực hiện Verification.

---

## 11.4. Output

```json
{
  "verified_evidence": [
    {
      "evidence_id": "EV001",
      "candidate_id": "EC001",
      "chunk_id": "C001",
      "document_id": "D001",
      "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
      "verification_status": "supported"
    }
  ],
  "needs_disclaimer": false
}
```

---

# 12. Handling Unsupported Claims

Nếu LLM sinh claim nằm ngoài Evidence Candidates:

```text
LLM Answer
    ↓
Claim
    ↓
Evidence Verification
    ↓
Không tìm thấy Evidence support
    ↓
unsupported
```

Claim đó không được xem là đã được chứng minh bởi nguồn pháp lý.

PoC ban đầu tập trung vào việc phát hiện và đánh dấu unsupported claims.

Cơ chế regeneration/self-correction có thể được xem xét ở version sau.

---

# 13. Contract 8 — Verified Evidence

## 13.1. Internal Evidence

Internal Evidence dùng trong AI Core, Verification, Debugging và Evaluation.

```json
{
  "evidence_id": "EV001",
  "chunk_id": "C001",
  "document_id": "D001",
  "content": "Hồ sơ đăng ký hộ kinh doanh gồm...",
  "title": "Đăng ký hộ kinh doanh",
  "document_type": "Nghị định",
  "article": "...",
  "clause": "...",
  "page": 4,
  "source_url": "...",
  "retrieval_score": 0.92,
  "rerank_score": 0.95,
  "verification_status": "supported"
}
```

### Traceability

```text
document_id
     ↓
chunk_id
     ↓
evidence_id
```

---

# 14. Contract 9 — Evidence Mapper

## 14.1. Responsibility

Evidence Mapper chuyển Internal / Verified Evidence thành API Evidence phù hợp cho Frontend.

Flow:

```text
Verified Evidence
      ↓
Evidence Mapper
      ↓
API Evidence
```

---

## 14.2. API Evidence

```json
{
  "source_id": "1",
  "document_id": "D001",
  "title": "Nghị định 01/2021, Điều 5",
  "snippet": "Hồ sơ đăng ký hộ kinh doanh gồm...",
  "page_number": 4
}
```

### API Fields

| Field | Type | Description |
|---|---|---|
| `source_id` | string | Citation index |
| `document_id` | string | ID tài liệu |
| `title` | string | Tên nguồn |
| `snippet` | string | Đoạn trích hiển thị |
| `page_number` | integer/null | Số trang nếu có |

---

# 15. Citation Contract

`source_id` được đánh theo **thứ tự citation xuất hiện trong answer**.

Ví dụ:

```text
Theo quy định [1], ...
Trong trường hợp này [2], ...
```

Mapping:

```text
[1] → Evidence 1
[2] → Evidence 2
```

`source_id` không được dùng làm ranking score.

---

# 16. End-to-End Contract

```text
                    ┌──────────────┐
                    │ User Query   │
                    └──────┬───────┘
                           ↓
                  ┌─────────────────┐
                  │ Context Manager │
                  └───────┬─────────┘
                         ↓
              Query Analysis / Multi-agent
                         ↓
          ┌────────────────────────────────┐
          │        ConsolidatedQuery       │
          │                                │
          │ resolved_query                 │
          │ original_query                 │
          │ needs_clarification            │
          │ clarification_question         │
          └───────────────┬────────────────┘
                          ↓
                 needs_clarification?
                    ┌─────┴─────┐
                    │           │
                  True        False
                    │           │
                    ↓           ↓
          Clarification     resolved_query
             Response            ↓
                              Official
                              Retrieval
                                 ↓
                            Retrieved Chunks
                                 ↓
                            ┌───────────┐
                            │ Reranking │
                            └─────┬─────┘
                                  ↓
                       Retrieved Chunks + Score
                                  ↓
                         Evidence Builder
                                  ↓
                        Evidence Candidates
                                  ↓
                        RAG Context Assembly
                                  ↓
                              ┌───────┐
                              │  LLM  │
                              └───┬───┘
                                  ↓
                                Answer
                                  ↓
                        Evidence Verification
                                  ↓
                          Verified Evidence
                                  ↓
                           Evidence Mapper
                                  ↓
                       Final Answer + [1][2]
```

### Day 1 Multi-agent Detail

```text
                 User Query + Context
                         │
             ┌───────────┴───────────┐
             ↓                       ↓
      history_reader         procedure_reader
             │                       │
             │ history               │ procedure/topic hint
             └───────────┬───────────┘
                         ↓
                    synthesizer
                         │
                         ↓
                ConsolidatedQuery
                         │
                  needs_clarification?
                    ┌────┴────┐
                    │         │
                  True      False
                    │         │
                    ↓         ↓
             Clarification   resolved_query
               Response          │
                                 ↓
                         Official Retrieval
```

`procedure_reader` Retrieval và Official Retrieval là hai calls riêng biệt với hai trách nhiệm khác nhau.


# 17. Responsibility Boundary

| Module | Responsible | Not Responsible |
|---|---|---|
| Context Manager | Conversation + Memory Context | Retrieval / Evidence |
| history_reader | Read and prepare conversation history | LLM / Retrieval |
| procedure_reader | Retrieve lightweight procedure/topic hints | Official Retrieval / Final answer |
| synthesizer | Create ConsolidatedQuery and clarification decision | Final answer / Evidence |
| Retrieval | Search legal chunks | Verify answer |
| Reranking | Re-score / reorder chunks | Legal verification |
| Evidence Builder | Prepare candidate evidence | Final evidence decision |
| RAG Context Assembly | Prepare LLM context | Verification |
| LLM | Generate answer | Final evidence validation |
| Evidence Verification | Validate claims against candidates | Full retrieval |
| Evidence Mapper | API representation | Verification |

---

# 18. Traceability Contract

Hệ thống phải duy trì traceability:

```text
Document
   ↓
Chunk
   ↓
Evidence Candidate
   ↓
Verified Evidence
   ↓
Citation
```

Các ID không được tự ý thay đổi hoặc mất trong quá trình xử lý:

```text
document_id
chunk_id
evidence_id
```

---

# 19. Current PoC Scope

## Included

- Context Object
- Conversation Summary
- Recent Messages
- Structured Context
- Basic Long-term Memory
- Retrieval
- Vector Search
- Top-K
- Reranking interface
- Evidence Builder
- Evidence Candidates
- RAG Context Assembly
- LLM Generation
- Evidence Verification
- Verified Evidence
- Evidence Mapper
- Citation
- ConsolidatedQuery
- Clarification fields in AnswerResponse:
  - `needs_clarification`
  - `clarification_question`

## Deferred

- Advanced semantic Long-term Memory
- Vector retrieval riêng cho Memory
- Advanced self-correction / regeneration
- Advanced claim extraction
- Final Reranker model selection
- Performance optimization
- Advanced evaluation

---

# 20. Open Questions

Các vấn đề chưa được freeze hoàn toàn:

1. Thuật toán/model Reranking cụ thể.
2. Cách tính `rerank_score`.
3. Số lượng chunk giữ lại sau Reranking.
4. Verification theo toàn answer hay theo từng claim.
5. Cách xác định claim trong answer.
6. Cách xử lý answer có một hoặc nhiều unsupported claims.
7. Có cần regeneration/self-correction hay không.
8. Giới hạn `recent_messages` theo số message hay token budget.
9. Cơ chế cập nhật `conversation_summary`.
10. Quy tắc đưa thông tin vào Long-term Memory.
11. Cách triển khai semantic retrieval cho Long-term Memory ở các version sau.

---

# 21. Implementation Rule

Contract này là **Source of Truth** cho implementation.

Khi bắt đầu code:

```text
Contract
   ↓
Implementation
   ↓
Unit Test
   ↓
Cross-module Test
   ↓
Integration
```

Nếu implementation phát sinh yêu cầu thay đổi Contract:

1. Ghi nhận vấn đề.
2. Thảo luận với cả nhóm.
3. Cập nhật Contract.
4. Chỉ sau khi thống nhất mới thay đổi implementation.

Không tự ý thay đổi Input / Output giữa các module.

---

# 22. ConsolidatedQuery Integration Note

`ConsolidatedQuery` là contract trung gian giữa Query Analysis / Multi-agent và Official Retrieval.

```text
User Query
    ↓
history_reader
    ↓
procedure_reader
    ↓
synthesizer
    ↓
ConsolidatedQuery
    ├── needs_clarification = true
    │       ↓
    │   Clarification Response
    │
    └── needs_clarification = false
            ↓
       resolved_query
            ↓
       Official Retrieval
```

`original_query` được giữ bởi Python từ query đầu vào và không phụ thuộc vào output của LLM.

`resolved_query`, `needs_clarification` và `clarification_question` là các field được `synthesizer` suy luận.

Không tạo một response class riêng cho clarification. Clarification sử dụng `AnswerResponse` hiện tại với hai field:

```text
needs_clarification
clarification_question
```

Normal answer:

```text
needs_clarification = false
clarification_question = null
```

Clarification response:

```text
needs_clarification = true
clarification_question = <question>
answer = null
claims = []
```
