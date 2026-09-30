"""
Query processing, embedding and vector search.

Return RetrievedChunk objects.
"""

import re
from dataclasses import dataclass

import chromadb
from sentence_transformers import SentenceTransformer

import my_config as cfg


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    retrieval_score: float
    metadata: dict


# =========================================================
# MODULE-LEVEL SINGLETONS
# Loaded once and reused across all queries
# =========================================================

_embedding_model: SentenceTransformer | None = None
_chroma_collection = None


# =========================================================
# MODEL / VECTOR STORE
# =========================================================

def load_embedding_model() -> SentenceTransformer:
    """
    Load embedding model only once.
    """
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = SentenceTransformer(
            cfg.EMBEDDING_MODEL
        )

    return _embedding_model


def load_vector_store():
    """
    Load existing persistent ChromaDB.
    """
    client = chromadb.PersistentClient(
        path=str(cfg.CHROMA_PATH)
    )

    collection = client.get_collection(
        name=cfg.COLLECTION_NAME
    )

    return collection


def _get_embedding_model() -> SentenceTransformer:
    """
    Return cached embedding model.
    Load on first call.
    """
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = load_embedding_model()

    return _embedding_model


def _get_chroma_collection():
    """
    Return cached Chroma collection.
    Load on first call.
    """
    global _chroma_collection

    if _chroma_collection is None:
        _chroma_collection = load_vector_store()

    return _chroma_collection


# =========================================================
# STRUCTURED CONTEXT HELPERS
# =========================================================

def _get_structured_context(
    context: dict | None
) -> dict:
    """
    Lấy structured_context từ Context Manager.

    Nếu structured_context chưa có thì thử fallback
    sang long_term_memory.
    """
    if not context:
        return {}

    structured_context = context.get(
        "structured_context",
        {}
    ) or {}

    if structured_context:
        return structured_context

    long_term_memory = context.get(
        "long_term_memory",
        {}
    ) or {}

    return long_term_memory


def _format_context_value(value) -> str:
    """
    Chuyển value của structured_context thành chuỗi
    phù hợp để đưa vào search query.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (list, tuple, set)):
        values = [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

        return ", ".join(values)

    return str(value).strip()


# =========================================================
# QUERY PROCESSING
# =========================================================

def build_search_query(
    query: str,
    context: dict | None = None
) -> str:
    """
    Build retrieval query using:
    - current user query
    - structured_context
    - long_term_memory fallback

    Các field quan trọng được đưa vào theo thứ tự ưu tiên.
    """

    query = (query or "").strip()

    if not query:
        return ""

    structured_context = _get_structured_context(
        context
    )

    if not structured_context:
        return query

    # Các field ảnh hưởng trực tiếp đến retrieval.
    priority_fields = [
        "procedure_name",
        "location",
        "intent",
        "method",
        "applicant_type",
        "documents",
        "fee",
        "processing_time",
    ]

    context_parts = []

    for key in priority_fields:

        value = structured_context.get(key)

        formatted_value = _format_context_value(
            value
        )

        if not formatted_value:
            continue

        # Dùng label tiếng Việt tự nhiên hơn cho embedding.
        labels = {
            "procedure_name": "thủ tục",
            "location": "địa phương",
            "intent": "nhu cầu",
            "method": "phương thức",
            "applicant_type": "đối tượng",
            "documents": "giấy tờ",
            "fee": "lệ phí",
            "processing_time": "thời gian xử lý",
        }

        label = labels.get(
            key,
            key
        )

        context_parts.append(
            f"{label}: {formatted_value}"
        )

    if not context_parts:
        return query

    return (
        query
        + " | "
        + " | ".join(context_parts)
    )


def _normalize_words(text: str) -> set[str]:
    """
    Convert text into useful lowercase words.
    """
    if not text:
        return set()

    words = re.findall(
        r"\w+",
        text.lower(),
        flags=re.UNICODE
    )

    stopwords = {
        "thủ",
        "tục",
        "cần",
        "những",
        "giấy",
        "tờ",
        "gì",
        "là",
        "có",
        "không",
        "để",
        "và",
        "các",
        "hồ",
        "sơ",
        "tôi",
        "muốn",
        "hỏi",
        "về",
    }

    return {
        word
        for word in words
        if word not in stopwords
    }


def _calculate_keyword_bonus(
    query: str,
    metadata: dict,
    content: str
) -> float:
    """
    Prefer results whose title/content directly matches
    important words in the retrieval query.
    """

    query_words = _normalize_words(
        query
    )

    title = str(
        metadata.get(
            "title",
            ""
        )
    )

    title_words = _normalize_words(
        title
    )

    content_words = _normalize_words(
        content
    )

    if not query_words:
        return 0.0

    title_overlap = len(
        query_words.intersection(
            title_words
        )
    )

    content_overlap = len(
        query_words.intersection(
            content_words
        )
    )

    # Title match is more important.
    bonus = (
        title_overlap * 0.30
        + content_overlap * 0.03
    )

    return bonus


def _calculate_context_bonus(
    structured_context: dict,
    metadata: dict,
    content: str
) -> float:
    """
    Tăng điểm nhẹ khi candidate phù hợp với
    procedure_name/location từ structured_context.

    Không filter cứng để tránh làm mất kết quả đúng
    khi metadata chưa đầy đủ.
    """

    if not structured_context:
        return 0.0

    bonus = 0.0

    searchable_text = " ".join(
        [
            str(metadata.get("title", "")),
            str(metadata.get("location", "")),
            str(metadata.get("procedure_name", "")),
            content or "",
        ]
    ).lower()

    procedure_name = _format_context_value(
        structured_context.get(
            "procedure_name"
        )
    )

    location = _format_context_value(
        structured_context.get(
            "location"
        )
    )

    if (
        procedure_name
        and procedure_name.lower()
        in searchable_text
    ):
        bonus += 0.35

    if (
        location
        and location.lower()
        in searchable_text
    ):
        bonus += 0.15

    return bonus


# =========================================================
# RETRIEVAL
# =========================================================

def retrieve(
    query: str,
    context: dict | None = None,
    top_k: int = cfg.DEFAULT_TOP_K
) -> list[RetrievedChunk]:
    """
    Retrieve relevant chunks.

    Flow:
    1. Build search query with structured context
    2. Vector search
    3. Keyword bonus
    4. Structured-context bonus
    5. Sort and return top_k
    """

    if not query or not query.strip():
        return []

    if top_k <= 0:
        return []

    structured_context = (
        _get_structured_context(
            context
        )
    )

    search_query = build_search_query(
        query=query,
        context=context
    )

    # =====================================================
    # EMBEDDING
    # =====================================================

    model = _get_embedding_model()

    query_embedding = model.encode(
        search_query,
        normalize_embeddings=True
    ).tolist()

    # =====================================================
    # VECTOR STORE
    # =====================================================

    collection = _get_chroma_collection()

    collection_count = collection.count()

    candidate_count = min(
        max(top_k * 5, 10),
        collection_count
    )

    if candidate_count <= 0:
        return []

    results = collection.query(
        query_embeddings=[
            query_embedding
        ],
        n_results=candidate_count
    )

    documents = results.get(
        "documents",
        [[]]
    )[0]

    metadatas = results.get(
        "metadatas",
        [[]]
    )[0]

    distances = results.get(
        "distances",
        [[]]
    )[0]

    retrieved_chunks = []

    # =====================================================
    # RANKING
    # =====================================================

    for content, metadata, distance in zip(
        documents,
        metadatas,
        distances
    ):

        metadata = metadata or {}

        content = content or ""

        chunk_id = str(
            metadata.get(
                "chunk_id",
                ""
            )
        )

        document_id = str(
            metadata.get(
                "document_id",
                ""
            )
        )

        # Vector score: higher is better.
        vector_score = 1.0 / (
            1.0 + float(distance)
        )

        # Dùng search_query thay vì query gốc
        # để keyword ranking cũng nhận context.
        keyword_bonus = (
            _calculate_keyword_bonus(
                query=search_query,
                metadata=metadata,
                content=content
            )
        )

        context_bonus = (
            _calculate_context_bonus(
                structured_context=(
                    structured_context
                ),
                metadata=metadata,
                content=content
            )
        )

        final_score = (
            vector_score
            + keyword_bonus
            + context_bonus
        )

        retrieved_chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                retrieval_score=final_score,
                metadata=metadata
            )
        )

    # Highest score first.
    retrieved_chunks.sort(
        key=lambda item: (
            item.retrieval_score
        ),
        reverse=True
    )

    return retrieved_chunks[:top_k]


# =========================================================
# GĐ2 MỤC 7: TWO-STEP RETRIEVAL
# =========================================================

def _is_ambiguous_query(query: str) -> bool:
    """
    Phát hiện query mơ hồ — không có từ khóa thủ tục cụ thể.
    Dùng để quyết định có hỏi làm rõ không.
    """
    # Query dưới 5 từ và không có keyword thủ tục = mơ hồ
    words = query.strip().split()
    if len(words) <= 4:
        return True

    # Các từ chỉ định thủ tục cụ thể
    try:
        from rag.synthesizer import _PROCEDURE_KEYWORDS
        specific_markers = _PROCEDURE_KEYWORDS
    except ImportError:
        specific_markers = {
            "kết hôn", "khai sinh", "khai tử", "nhận cha", "nhận mẹ", "nhận con",
            "hôn nhân", "tình trạng hôn nhân", "xác nhận tình trạng",
            "hộ kinh doanh", "xây dựng", "khuyết tật", "chuyển trường",
            "học bổng", "chứng thực", "đất đai", "tạm ngừng kinh doanh",
            "hưu trí", "trợ cấp", "liệt sĩ", "mai táng", "hỏa táng",
            "vay vốn", "việc làm", "hộ tịch",
        }
    q_lower = query.lower()
    return not any(m in q_lower for m in specific_markers)


def retrieve_two_step(
    query: str,
    context: dict | None = None,
    top_k: int = cfg.DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """
    GĐ2 mục 7: Retrieval hai bước để tránh nhầm thủ tục.

    Bước 1: Xác định document_id từ chunk _general (tổng quan).
    Bước 2: Lấy chunk field cụ thể (_docs/_fee/_time/_method)
            chỉ của document đó, theo _detect_field_types.

    Fallback: nếu không tìm được doc_id rõ ràng → dùng retrieve() thường.

    Clarification: nếu top-1 và top-2 thuộc các thủ tục khác nhau sát nhau (<0.08 delta),
    không có thủ tục đang active, và query mơ hồ → trả []
    (pipeline sẽ trả clarification).
    """
    if not query or not query.strip():
        return []

    # ---- Bước 1: xác định document_id ----
    # Chạy vector search trên toàn collection để tìm chunk tốt nhất
    raw_results = retrieve(query=query, context=context, top_k=top_k * 3)

    if not raw_results:
        return []

    # Ambiguity check: so sánh top chunk thuộc các document_id KHÁC NHAU
    distinct_doc_chunks = []
    seen_docs = set()
    for chunk in raw_results:
        if chunk.document_id not in seen_docs:
            distinct_doc_chunks.append(chunk)
            seen_docs.add(chunk.document_id)

    if (
        len(distinct_doc_chunks) >= 2
        and _is_ambiguous_query(query)
        and (distinct_doc_chunks[0].retrieval_score - distinct_doc_chunks[1].retrieval_score) < 0.08
    ):
        # Lấy context hiện tại để xem có thủ tục đang active không
        structured_context = _get_structured_context(context)
        active_procedure = structured_context.get("procedure_name", "")
        if not active_procedure:
            # Trả [] để pipeline biết cần hỏi clarification
            print(
                f"[retrieval] Ambiguous query, top distinct doc scores close: "
                f"{distinct_doc_chunks[0].document_id} ({distinct_doc_chunks[0].retrieval_score:.3f}) vs "
                f"{distinct_doc_chunks[1].document_id} ({distinct_doc_chunks[1].retrieval_score:.3f}) — trigger clarification"
            )
            return []

    # Lấy top document_id từ _general hoặc bất kỳ chunk nào
    doc_scores: dict[str, float] = {}
    for chunk in raw_results:
        doc_id = chunk.document_id
        # Chunk _general được ưu tiên hơn
        weight = 1.2 if chunk.chunk_id.endswith("_general") else 1.0
        score = chunk.retrieval_score * weight
        if doc_id not in doc_scores or score > doc_scores[doc_id]:
            doc_scores[doc_id] = score

    # document_id tốt nhất
    best_doc_id = max(doc_scores, key=lambda d: doc_scores[d])
    best_score = doc_scores[best_doc_id]

    # Nếu doc_id rõ ràng (score cao vượt trội hoặc context đã có)
    structured_context = _get_structured_context(context)
    active_procedure = structured_context.get("procedure_name", "")

    # Nếu context đã có thủ tục đang active, ưu tiên nó
    if active_procedure:
        for chunk in raw_results:
            if active_procedure.lower() in (
                chunk.metadata.get("title", "") + chunk.content
            ).lower():
                best_doc_id = chunk.document_id
                break

    print(f"[retrieval] Two-step: best_doc_id={best_doc_id} score={best_score:.3f}")

    # ---- Bước 2: lấy field chunk của đúng document đó ----
    # Detect field từ query
    try:
        from rag.prompt_builder import _detect_field_types
        field_types = _detect_field_types(query=query, context=context)
    except ImportError:
        field_types = []

    # Lọc chunk: chỉ lấy từ best_doc_id, ưu tiên field chunk đúng loại
    doc_chunks = [c for c in raw_results if c.document_id == best_doc_id]

    if field_types and doc_chunks:
        field_suffixes = {
            "docs": "_docs",
            "fee": "_fee",
            "time": "_time",
            "method": "_method",
        }

        if len(field_types) >= 2:
            # Multi-intent quota allocation:
            # Ensure every detected intent/field gets dedicated chunks, plus 1 general chunk if available.
            selected_chunks = []
            seen_ids = set()

            general_chunks = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
            quota_per_field = max(1, (top_k - 1) // len(field_types))

            for ftype in field_types:
                suf = field_suffixes.get(ftype)
                if not suf:
                    continue
                matching = [
                    c for c in doc_chunks
                    if c.chunk_id.endswith(suf) and c.chunk_id not in seen_ids
                ]
                matching.sort(key=lambda c: c.retrieval_score, reverse=True)
                for c in matching[:quota_per_field]:
                    selected_chunks.append(c)
                    seen_ids.add(c.chunk_id)

            # Add general chunk for overall context if available
            for gc in general_chunks:
                if gc.chunk_id not in seen_ids and len(selected_chunks) < top_k:
                    selected_chunks.append(gc)
                    seen_ids.add(gc.chunk_id)

            # Fill remaining slots with highest scoring remaining chunks of best_doc_id
            remaining = [c for c in doc_chunks if c.chunk_id not in seen_ids]
            remaining.sort(key=lambda c: c.retrieval_score, reverse=True)
            for c in remaining:
                if len(selected_chunks) < top_k:
                    selected_chunks.append(c)
                    seen_ids.add(c.chunk_id)

            return selected_chunks[:top_k]
        else:
            target_suffixes = {field_suffixes[f] for f in field_types if f in field_suffixes}

            # Ưu tiên chunk đúng field; nếu không tìm thấy thì lấy _general
            targeted = [c for c in doc_chunks if any(
                c.chunk_id.endswith(s) for s in target_suffixes
            )]
            if not targeted:
                targeted = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
            if not targeted:
                targeted = doc_chunks

            # Thêm _general của doc này vào cuối (cho context tổng quát)
            general_chunks = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
            result = targeted[:top_k]
            for gc in general_chunks:
                if gc not in result and len(result) < top_k:
                    result.append(gc)
            return result[:top_k]

    # Không có field cụ thể → lấy _general của doc này + top chunks khác
    result = sorted(doc_chunks, key=lambda c: c.retrieval_score, reverse=True)
    if len(result) < top_k:
        # Bổ sung từ raw_results của doc khác
        for c in raw_results:
            if c.document_id != best_doc_id and len(result) < top_k:
                result.append(c)
    return result[:top_k]