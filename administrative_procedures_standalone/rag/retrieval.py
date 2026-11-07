"""
Query processing, embedding and vector search.

Return RetrievedChunk objects.
"""

import re
from dataclasses import dataclass

from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import ScoredPoint

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

_embedding_model = None
_qdrant_client: QdrantClient | None = None


# =========================================================
# MODEL / VECTOR STORE
# =========================================================

def load_embedding_model():
    """
    Load BGE-M3 embedding model using SentenceTransformer (prefer local cache).
    """
    global _embedding_model

    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        print(f"[retrieval] Loading BGE-M3 model using SentenceTransformer ('BAAI/bge-m3')...")
        try:
            _embedding_model = SentenceTransformer("BAAI/bge-m3", local_files_only=True)
        except Exception:
            _embedding_model = SentenceTransformer("BAAI/bge-m3")
        _embedding_model.max_seq_length = 512

    return _embedding_model


import atexit

def load_vector_store() -> QdrantClient:
    """
    Load Qdrant client connection (Cloud if configured, local directory fallback).
    """
    global _qdrant_client

    if _qdrant_client is None:
        if cfg.QDRANT_URL:
            print(f"[retrieval] Connecting to Qdrant Cloud at {cfg.QDRANT_URL}")
            _qdrant_client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY, timeout=60)
        else:
            local_path = cfg.BASE_DIR / "data" / "qdrant_db"
            local_path.mkdir(parents=True, exist_ok=True)
            print(f"[retrieval] QDRANT_URL not set, using local Qdrant at {local_path}")
            _qdrant_client = QdrantClient(path=str(local_path))
            atexit.register(close_vector_store)

    return _qdrant_client

def close_vector_store():
    """Close QdrantClient instance to release file locks."""
    global _qdrant_client
    if _qdrant_client is not None:
        try:
            _qdrant_client.close()
        except Exception as exc:
            print(f"[retrieval] Warning closing Qdrant client: {exc}")
        _qdrant_client = None


def _get_embedding_model():
    """
    Return cached embedding model.
    Load on first call.
    """
    global _embedding_model

    if _embedding_model is None:
        _embedding_model = load_embedding_model()

    return _embedding_model


def _get_qdrant_client() -> QdrantClient:
    """
    Return cached Qdrant client.
    Load on first call.
    """
    global _qdrant_client

    if _qdrant_client is None:
        _qdrant_client = load_vector_store()

    return _qdrant_client


from collections import OrderedDict

_QUERY_EMBEDDING_CACHE: OrderedDict[str, list[float]] = OrderedDict()
_MAX_EMBEDDING_CACHE_SIZE = 1000

def encode_query(query: str) -> list[float]:
    """Encode query string into 1024-dim BGE-M3 dense vector with LRU cache."""
    clean_q = (query or "").strip().lower()
    if not clean_q:
        return []
    if clean_q in _QUERY_EMBEDDING_CACHE:
        _QUERY_EMBEDDING_CACHE.move_to_end(clean_q)
        return _QUERY_EMBEDDING_CACHE[clean_q]

    model = _get_embedding_model()
    vec = model.encode(query, normalize_embeddings=True)
    res = vec.tolist() if hasattr(vec, "tolist") else list(vec)
    if len(_QUERY_EMBEDDING_CACHE) >= _MAX_EMBEDDING_CACHE_SIZE:
        _QUERY_EMBEDDING_CACHE.popitem(last=False)
    _QUERY_EMBEDDING_CACHE[clean_q] = res
    return res


# =========================================================
# STRUCTURED CONTEXT HELPERS
# =========================================================

def _get_structured_context(
    context: dict | None
) -> dict:
    """
    Lấy structured_context từ Context Manager.
    """
    if not context:
        return {}

    return context.get(
        "structured_context",
        {}
    ) or {}


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
    - current user query (normalized)
    - structured_context
    """
    from rag.text_normalizer import normalize_query_text

    query = normalize_query_text((query or "").strip())

    if not query:
        return ""

    structured_context = _get_structured_context(
        context
    )

    if not structured_context:
        return query

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
    Convert text into useful lowercase words, including folded accents for cross-matching.
    Filters generic administrative/question stopwords so keyword bonus reflects true subject match.
    """
    if not text:
        return set()

    from rag.text_normalizer import fold_accents, normalize_query_text
    norm_text = normalize_query_text(text)

    words = re.findall(
        r"\w+",
        norm_text.lower(),
        flags=re.UNICODE
    )

    stopwords = {
        "thủ", "tục", "cần", "những", "giấy", "tờ", "gì", "là", "có", "không",
        "để", "và", "các", "hồ", "sơ", "tôi", "muốn", "hỏi", "về", "bao", "nhiêu",
        "thu", "tuc", "can", "nhung", "giay", "to", "gi", "la", "co", "khong",
        "de", "va", "cac", "ho", "so", "toi", "muon", "hoi", "ve", "bao", "nhieu", "mat",
        "xin", "cấp", "cap", "làm", "lam", "nộp", "nop", "ở", "đâu", "dau", "tại", "tai",
        "thời", "gian", "thoi", "hạn", "han", "giải", "quyết", "giai", "quyet",
        "lâu", "lau", "ngày", "ngay", "việc", "viec", "lệ", "phí", "le", "phi",
        "tiền", "tien", "gồm", "gom", "chuẩn", "bị", "chuan", "bi", "nào", "nao",
        "theo", "hình", "thức", "hinh", "thuc", "cho", "của", "cua", "trong", "khi",
        "mấy", "may", "tốn", "ton", "mang",
    }

    base_words = {
        word
        for word in words
        if word not in stopwords and len(word) > 1
    }
    folded_words = {fold_accents(w) for w in base_words if len(w) > 1}
    return base_words | folded_words


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

    is_neg = _is_negated_phrase(title, query)
    if is_neg:
        bonus = content_overlap * 0.03
    else:
        bonus = (
            title_overlap * 0.30
            + content_overlap * 0.03
        )

    return bonus


def _is_negated_phrase(phrase: str, text: str) -> bool:
    """Check if a phrase or procedure alias is negated by 'chưa', 'không', etc."""
    if not phrase or not text:
        return False
    phrase_clean = phrase.strip().lower()
    text_clean = text.strip().lower()
    if phrase_clean.startswith("chưa") or phrase_clean.startswith("không"):
        return False
    pattern = r"(chưa|không|chẳng|chưa từng)\s+(đăng ký\s+|làm\s+|xin\s+)?" + re.escape(phrase_clean)
    return bool(re.search(pattern, text_clean))


_ALIAS_CATALOG: dict[str, dict[str, list[str]]] = {}

def _get_alias_catalog(domain: str | None = None) -> dict[str, list[str]]:
    global _ALIAS_CATALOG
    d_id = domain or "administrative_procedures"
    if d_id not in _ALIAS_CATALOG:
        catalog = {}
        try:
            import json
            from domains.runtime import get_domain_runtime
            runtime = get_domain_runtime(d_id)

            sources = runtime.config.sources if (runtime and hasattr(runtime, "config")) else []
            data_file = None
            for src in sources:
                if src.get("type") == "json" and src.get("path"):
                    data_file = cfg.BASE_DIR / src["path"]
                    break

            if not data_file or not data_file.exists():
                data_file = cfg.BASE_DIR / "data" / "procedures.json"

            if data_file.exists():
                items = json.loads(data_file.read_text(encoding="utf-8"))
                for p in items:
                    did = p.get("document_id") or p.get("id")
                    aliases = p.get("aliases", [])
                    if did and aliases:
                        catalog[did] = [a.lower().strip() for a in aliases if a]
        except Exception as e:
            print(f"[retrieval] Could not load alias catalog for {d_id}: {e}")
        _ALIAS_CATALOG[d_id] = catalog
    return _ALIAS_CATALOG[d_id]


def _calculate_alias_bonus(
    query: str,
    doc_id: str,
    metadata: dict,
    domain: str | None = None,
) -> float:
    """
    Check if query matches any alias of this procedure.
    Exact phrase match gets strong bonus (+0.85).
    """
    catalog = _get_alias_catalog(domain=domain)
    aliases = metadata.get("aliases") or catalog.get(doc_id, [])
    if not aliases:
        return 0.0

    from rag.text_normalizer import fold_accents, normalize_query_text
    q_norm = normalize_query_text(query).lower()
    q_folded = fold_accents(q_norm)
    best = 0.0
    for alias in aliases:
        if not alias:
            continue
        if _is_negated_phrase(alias, q_norm):
            continue
        a_folded = fold_accents(alias)
        if alias in q_norm or (len(a_folded) >= 4 and a_folded in q_folded):
            best = max(best, 0.85)
            continue
        alias_words = _normalize_words(alias)
        q_words = _normalize_words(query)
        if alias_words and alias_words.issubset(q_words):
            best = max(best, 0.55)
        elif len(alias_words.intersection(q_words)) >= 2:
            best = max(best, 0.25)
    return best


def _calculate_context_bonus(
    structured_context: dict,
    metadata: dict,
    content: str
) -> float:
    """
    Tăng điểm nhẹ khi candidate phù hợp với
    procedure_name/location từ structured_context.
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


def _calculate_field_bonus(chunk_id: str, metadata: dict, field_types: list[str]) -> float:
    """Reward chunks whose field matches the user's requested field intent."""
    if not field_types:
        return 0.0
    field_suffixes = {
        "docs": "_docs",
        "fee": "_fee",
        "time": "_time",
        "method": "_method",
    }
    field_meta_names = {
        "docs": "required_documents",
        "fee": "fee",
        "time": "processing_time",
        "method": "submission_method",
    }
    cid = str(chunk_id or "")
    meta_field = str((metadata or {}).get("field", "") or "")
    if meta_field == "submission_location":
        meta_field = "submission_method"

    for idx, ftype in enumerate(field_types):
        suf = field_suffixes.get(ftype)
        mname = field_meta_names.get(ftype)
        if (suf and cid.endswith(suf)) or (mname and meta_field == mname):
            return 0.55 if idx == 0 else 0.35
    return 0.0


# =========================================================
# RETRIEVAL
# =========================================================

def retrieve(
    query: str,
    context: dict | None = None,
    top_k: int = cfg.DEFAULT_TOP_K,
    domain: str | None = None,
) -> list[RetrievedChunk]:
    """
    Retrieve relevant chunks using Qdrant vector search and BGE-M3 embeddings.
    """

    if not query or not query.strip():
        return []

    if top_k <= 0:
        return []

    structured_context = _get_structured_context(context)
    search_query = build_search_query(query=query, context=context)

    try:
        from rag.prompt_builder import _detect_field_types
        field_types = _detect_field_types(query=query, context=context, domain=domain)
    except Exception:
        field_types = []

    # =====================================================
    # EMBEDDING
    # =====================================================
    query_embedding = encode_query(search_query)

    # =====================================================
    # VECTOR STORE
    # =====================================================
    client = _get_qdrant_client()
    from domains.runtime import get_domain_runtime
    runtime = get_domain_runtime(domain)
    collection_name = runtime.collection_name
    candidate_count = max(top_k * 8, 50)

    if candidate_count <= 0:
        return []

    try:
        query_response = client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            limit=candidate_count,
            with_payload=True,
        )
        hits = query_response.points if hasattr(query_response, "points") else query_response
    except Exception as e:
        print(f"[retrieval] Qdrant query_points error: {e}")
        return []

    retrieved_chunks = []

    # =====================================================
    # RANKING
    # =====================================================
    for hit in hits:
        payload = dict(getattr(hit, "payload", {}) or {})
        score = getattr(hit, "score", 0.0)

        content = payload.get("text") or payload.get("content") or ""
        chunk_id = str(payload.get("chunk_id", getattr(hit, "id", "")))
        document_id = str(payload.get("document_id", ""))

        vector_score = float(score)

        keyword_bonus = _calculate_keyword_bonus(
            query=search_query,
            metadata=payload,
            content=content,
        )

        alias_bonus = _calculate_alias_bonus(
            query=query,
            doc_id=document_id,
            metadata=payload,
            domain=domain,
        )

        context_bonus = _calculate_context_bonus(
            structured_context=structured_context,
            metadata=payload,
            content=content,
        )

        field_bonus = _calculate_field_bonus(
            chunk_id=chunk_id,
            metadata=payload,
            field_types=field_types,
        )

        negation_penalty = 0.0
        q_lower = query.lower()
        if _is_negated_phrase("kết hôn", q_lower) and document_id in ("PROC_004", "PROC_006"):
            negation_penalty = 1.50
        elif any(_is_negated_phrase(a, q_lower) for a in (payload.get("aliases") or [])):
            negation_penalty = 0.60

        doc_base_score = vector_score + keyword_bonus + alias_bonus + context_bonus - negation_penalty
        final_score = doc_base_score + field_bonus

        payload["_vector_score"] = vector_score
        payload["_doc_base_score"] = doc_base_score

        retrieved_chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                content=content,
                retrieval_score=final_score,
                metadata=payload,
            )
        )

    # Out-of-scope gate for strict domain when no active conversation context exists
    if retrieved_chunks and not structured_context.get("procedure_name"):
        if runtime.mode == "strict":
            from rag.scope_classifier import classify_query_scope
            top_chunk = max(retrieved_chunks, key=lambda c: c.metadata.get("_doc_base_score", c.retrieval_score))
            top_title = str(top_chunk.metadata.get("title", "") or "")
            top_vec = float(top_chunk.metadata.get("_vector_score", 0.0))
            in_scope, _reason = classify_query_scope(
                query=query,
                top_doc_title=top_title,
                top_vector_score=top_vec,
                domain=domain,
            )
            if not in_scope:
                return []

    retrieved_chunks.sort(key=lambda item: item.retrieval_score, reverse=True)
    return retrieved_chunks[:top_k]


# =========================================================
# GĐ2 MỤC 7: TWO-STEP RETRIEVAL
# =========================================================

def _is_ambiguous_query(query: str, domain: str | None = None) -> bool:
    """
    Phát hiện query mơ hồ — không có từ khóa thủ tục cụ thể.
    Dùng để quyết định có hỏi làm rõ không.
    """
    q_lower = query.strip().lower()
    if not q_lower:
        return True

    from domains.runtime import get_domain_runtime
    from rag.text_normalizer import fold_accents
    runtime = get_domain_runtime(domain)
    specific_markers = runtime.entity_keywords
    q_folded = fold_accents(q_lower)

    if any(m.lower() in q_lower or fold_accents(m.lower()) in q_folded for m in specific_markers if m):
        return False

    catalog = _get_alias_catalog(domain=domain)
    for doc_id, aliases in catalog.items():
        if any(a in q_lower or fold_accents(a) in q_folded for a in aliases if a):
            return False

    cleaned = re.sub(
        r'\b(á|ạ|ơi|nha|nhé|với|hộ|giùm|chút|tí|cậu|bạn|anh|chị|em|ad|admin|nào|gì)\b',
        '',
        q_lower
    ).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)

    vague_phrases = [
        "xin chào", "chào", "chào bạn", "hello", "hi", "alo", "tôi muốn hỏi",
        "mình muốn hỏi", "tôi có câu hỏi", "mình có câu hỏi", "hỏi về thủ tục",
        "hỏi thủ tục", "muốn hỏi thủ tục", "mình muốn hỏi thủ tục", "tôi muốn hỏi thủ tục",
        "cho mình hỏi thủ tục", "cho tôi hỏi thủ tục", "cho mình hỏi", "cho tôi hỏi"
    ]
    if any(q_lower == v or cleaned == v or cleaned.startswith(v) for v in vague_phrases):
        return True

    words = cleaned.split()
    return len(words) <= 4


def retrieve_two_step(
    query: str,
    context: dict | None = None,
    top_k: int = cfg.DEFAULT_TOP_K,
    domain: str | None = None,
    raw_results: list[RetrievedChunk] | None = None,
) -> list[RetrievedChunk]:
    """
    GĐ2 mục 7: Retrieval hai bước để tránh nhầm thủ tục trên Qdrant.
    """
    if not query or not query.strip():
        return []

    # ---- Bước 1: xác định document_id ----
    if raw_results is None:
        raw_results = retrieve(query=query, context=context, top_k=max(top_k * 4, 20), domain=domain)

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
        and _is_ambiguous_query(query, domain=domain)
        and (distinct_doc_chunks[0].retrieval_score - distinct_doc_chunks[1].retrieval_score) < 0.08
    ):
        structured_context = _get_structured_context(context)
        active_procedure = structured_context.get("procedure_name", "")
        if not active_procedure:
            print(
                f"[retrieval] Ambiguous query, top distinct doc scores close: "
                f"{distinct_doc_chunks[0].document_id} ({distinct_doc_chunks[0].retrieval_score:.3f}) vs "
                f"{distinct_doc_chunks[1].document_id} ({distinct_doc_chunks[1].retrieval_score:.3f}) — trigger clarification"
            )
            return []

    # Tính điểm cấp document dựa trên _doc_base_score (tránh cộng đúp alias_bonus hoặc bị field_bonus làm lệch doc)
    doc_scores: dict[str, float] = {}
    q_lower = query.lower()

    for chunk in raw_results:
        doc_id = chunk.document_id
        base_s = float(chunk.metadata.get("_doc_base_score", chunk.retrieval_score))
        weight = 1.03 if chunk.chunk_id.endswith("_general") else 1.0
        score = base_s * weight
        if doc_id not in doc_scores or score > doc_scores[doc_id]:
            doc_scores[doc_id] = score

    # Phạt các thủ tục kết hôn khi từ khóa kết hôn bị phủ định (ví dụ: chưa đăng ký kết hôn)
    if _is_negated_phrase("kết hôn", q_lower):
        for doc_id in list(doc_scores.keys()):
            if doc_id in ("PROC_004", "PROC_006"):
                doc_scores[doc_id] -= 1.50

    structured_context = _get_structured_context(context)
    active_procedure = str(structured_context.get("procedure_name", "")).strip()

    # Bước 2B: Điểm thưởng mềm (Soft Boost) cho active_procedure
    if active_procedure:
        active_lower = active_procedure.lower()
        for doc_id in doc_scores:
            is_active_match = any(
                active_lower in str(c.metadata.get("title", "")).lower()
                or active_lower == c.document_id.lower()
                for c in raw_results if c.document_id == doc_id
            )
            if is_active_match:
                doc_scores[doc_id] += 0.15

    ranked_doc_ids = sorted(doc_scores.keys(), key=lambda d: doc_scores[d], reverse=True)
    best_doc_id = ranked_doc_ids[0]
    best_score = doc_scores[best_doc_id]

    print(f"[retrieval] Two-step: best_doc_id={best_doc_id} score={best_score:.3f}")

    # ---- Bước 2: lấy field chunk của đúng document đó ----
    try:
        from rag.prompt_builder import _detect_field_types
        field_types = _detect_field_types(query=query, context=context, domain=domain)
    except ImportError:
        field_types = []

    doc_chunks = [c for c in raw_results if c.document_id == best_doc_id]

    if field_types and doc_chunks:
        field_suffixes = {
            "docs": "_docs",
            "fee": "_fee",
            "time": "_time",
            "method": "_method",
        }

        # Ensure all requested field chunks of best_doc_id are loaded even if truncated out of raw_results
        needed_sufs = [field_suffixes[f] for f in field_types if f in field_suffixes]
        missing_sufs = [s for s in needed_sufs if not any(c.chunk_id.endswith(s) for c in doc_chunks)]
        if missing_sufs:
            try:
                from domains.runtime import get_domain_runtime
                from qdrant_client.models import FieldCondition, Filter, MatchValue
                client = _get_qdrant_client()
                runtime = get_domain_runtime(domain)
                pts, _ = client.scroll(
                    collection_name=runtime.collection_name,
                    scroll_filter=Filter(
                        must=[FieldCondition(key="document_id", match=MatchValue(value=best_doc_id))]
                    ),
                    limit=20,
                    with_payload=True,
                )
                existing_cids = {c.chunk_id for c in doc_chunks}
                for pt in (pts or []):
                    pl = dict(getattr(pt, "payload", {}) or {})
                    cid = str(pl.get("chunk_id", getattr(pt, "id", "")))
                    if cid not in existing_cids:
                        f_bonus = _calculate_field_bonus(cid, pl, field_types)
                        pl["_doc_base_score"] = best_score
                        doc_chunks.append(
                            RetrievedChunk(
                                chunk_id=cid,
                                document_id=best_doc_id,
                                content=pl.get("text") or pl.get("content") or "",
                                retrieval_score=best_score + f_bonus,
                                metadata=pl,
                            )
                        )
                        existing_cids.add(cid)
            except Exception as e:
                print(f"[retrieval] Fallback scroll for {best_doc_id} failed: {e}")

        if len(field_types) >= 2:
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

            for gc in general_chunks:
                if gc.chunk_id not in seen_ids and len(selected_chunks) < top_k:
                    selected_chunks.append(gc)
                    seen_ids.add(gc.chunk_id)

            # Priority Slot Allocation: fill remaining slots with matching field chunks from next best docs
            primary_suf = field_suffixes.get(field_types[0], "")
            for next_doc_id in ranked_doc_ids[1:]:
                if len(selected_chunks) >= top_k:
                    break
                next_doc_chunks = [
                    c for c in raw_results
                    if c.document_id == next_doc_id and c.chunk_id not in seen_ids
                ]
                if primary_suf:
                    next_doc_chunks.sort(
                        key=lambda c: (1 if c.chunk_id.endswith(primary_suf) else 0, c.retrieval_score),
                        reverse=True,
                    )
                for c in next_doc_chunks[:1]:
                    if len(selected_chunks) < top_k:
                        selected_chunks.append(c)
                        seen_ids.add(c.chunk_id)

            return selected_chunks[:top_k]
        else:
            target_suffixes = {field_suffixes[f] for f in field_types if f in field_suffixes}

            targeted = [c for c in doc_chunks if any(
                c.chunk_id.endswith(s) for s in target_suffixes
            )]
            if not targeted:
                targeted = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
            if not targeted:
                targeted = doc_chunks

            general_chunks = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
            result = list(targeted[:top_k])
            for gc in general_chunks:
                if gc not in result and len(result) < top_k:
                    result.append(gc)

            # Priority Slot Allocation: fill remaining slots with targeted field chunks of next-best docs
            seen_ids = {c.chunk_id for c in result}
            for next_doc_id in ranked_doc_ids[1:]:
                if len(result) >= top_k:
                    break
                next_chunks = [
                    c for c in raw_results
                    if c.document_id == next_doc_id and c.chunk_id not in seen_ids
                ]
                next_targeted = [
                    c for c in next_chunks
                    if any(c.chunk_id.endswith(s) for s in target_suffixes)
                ]
                candidates_to_add = next_targeted if next_targeted else next_chunks
                candidates_to_add.sort(key=lambda c: c.retrieval_score, reverse=True)
                for c in candidates_to_add[:1]:
                    if len(result) < top_k:
                        result.append(c)
                        seen_ids.add(c.chunk_id)

            return result[:top_k]

    # Không có field cụ thể → lấy _general của doc này + top chunks khác
    result = sorted(doc_chunks, key=lambda c: c.retrieval_score, reverse=True)
    if len(result) < top_k:
        other_chunks = [c for c in raw_results if c.document_id != best_doc_id]
        other_chunks.sort(
            key=lambda c: (doc_scores.get(c.document_id, 0.0), c.retrieval_score),
            reverse=True,
        )
        for c in other_chunks:
            if len(result) < top_k:
                result.append(c)
    return result[:top_k]
