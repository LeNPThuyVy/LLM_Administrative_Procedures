from typing import Optional
from rag.multi.types import SubQuery, SubResult
from rag.retrieval import retrieve, RetrievedChunk, _is_ambiguous_query, _get_structured_context
from domains.runtime import get_domain_runtime
import my_config as cfg

def _filter_chunks_by_fields(doc_chunks: list[RetrievedChunk], fields: list[str], top_k: int) -> list[RetrievedChunk]:
    """
    Tái sử dụng logic bước 2 của retrieve_two_step: lọc chunk theo trường.
    """
    if not fields or not doc_chunks:
        # Lấy _general và top chunks
        general_chunks = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
        result = sorted(doc_chunks, key=lambda c: c.retrieval_score, reverse=True)
        return result[:top_k]

    field_suffixes = {
        "required_documents": "_docs",
        "docs": "_docs",
        "fee": "_fee",
        "processing_time": "_time",
        "time": "_time",
        "submission_method": "_method",
        "method": "_method",
    }
    
    selected_chunks = []
    seen_ids = set()
    general_chunks = [c for c in doc_chunks if c.chunk_id.endswith("_general")]
    
    if len(fields) >= 2:
        quota_per_field = max(1, (top_k - 1) // len(fields))
        
        for ftype in fields:
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
                
        remaining = [c for c in doc_chunks if c.chunk_id not in seen_ids]
        remaining.sort(key=lambda c: c.retrieval_score, reverse=True)
        for c in remaining:
            if len(selected_chunks) < top_k:
                selected_chunks.append(c)
                seen_ids.add(c.chunk_id)
                
        return selected_chunks[:top_k]
    else:
        target_suffixes = {field_suffixes[f] for f in fields if f in field_suffixes}
        targeted = [c for c in doc_chunks if any(c.chunk_id.endswith(s) for s in target_suffixes)]
        if not targeted:
            targeted = general_chunks
        if not targeted:
            targeted = doc_chunks
            
        result = targeted[:top_k]
        for gc in general_chunks:
            if gc not in result and len(result) < top_k:
                result.append(gc)
        return result[:top_k]

def resolve_sub_query(sub_query: SubQuery, context: dict | None, domain: str) -> SubResult:
    runtime = get_domain_runtime(domain)
    top_k = getattr(runtime.config, "max_chunks_per_procedure", 3)
    min_score = runtime.min_retrieval_score
    
    # Dùng raw_mention để retrieve
    query_text = sub_query.raw_mention
    
    # 1. Retrieve raw results
    raw_results = retrieve(query=query_text, context=context, top_k=cfg.DEFAULT_TOP_K * 3, domain=domain)
    
    if not raw_results:
        return SubResult(
            sub_query=sub_query,
            status="NOT_FOUND",
            document_id=None,
            chunks=[],
            suggested_title=None,
            score=0.0
        )
        
    # Nếu procedure_hint có sẵn, ưu tiên tìm doc có title khớp
    best_doc_id = None
    best_score = 0.0
    suggested_title = None
    
    if sub_query.procedure_hint:
        hint_lower = sub_query.procedure_hint.lower()
        for chunk in raw_results:
            title = chunk.metadata.get("title", "").lower()
            if hint_lower in title or title in hint_lower:
                best_doc_id = chunk.document_id
                best_score = chunk.retrieval_score
                suggested_title = chunk.metadata.get("title")
                break
                
    # Nếu không có procedure_hint hoặc không khớp, dùng logic best_doc_id của retrieve_two_step
    if not best_doc_id:
        doc_scores: dict[str, float] = {}
        for chunk in raw_results:
            doc_id = chunk.document_id
            weight = 1.2 if chunk.chunk_id.endswith("_general") else 1.0
            score = chunk.retrieval_score * weight
            if doc_id not in doc_scores or score > doc_scores[doc_id]:
                doc_scores[doc_id] = score
                
        best_doc_id = max(doc_scores, key=lambda d: doc_scores[d])
        best_score = doc_scores[best_doc_id]
        
        # Lấy suggested title từ doc_id này
        for c in raw_results:
            if c.document_id == best_doc_id:
                suggested_title = c.metadata.get("title")
                break
                
    # Kiểm tra AMBIGUOUS
    distinct_doc_chunks = []
    seen_docs = set()
    for chunk in raw_results:
        if chunk.document_id not in seen_docs:
            distinct_doc_chunks.append(chunk)
            seen_docs.add(chunk.document_id)
            
    if (
        len(distinct_doc_chunks) >= 2
        and _is_ambiguous_query(query_text, domain=domain)
        and (distinct_doc_chunks[0].retrieval_score - distinct_doc_chunks[1].retrieval_score) < 0.08
    ):
        return SubResult(
            sub_query=sub_query,
            status="AMBIGUOUS",
            document_id=None,
            chunks=[],
            suggested_title=None,
            score=best_score
        )
        
    # Phán quyết trạng thái
    # title_match_min logic (Phase 3 yêu cầu)
    title_match_min = getattr(runtime.config, "multi_intent", {}).get("title_match_min", 0.6)
    # Tạm thời nếu có procedure_hint thì coi như match 1.0, ngược lại match 1.0 nếu tìm thấy
    
    if best_score >= min_score:
        status = "FOUND"
    else:
        status = "NOT_FOUND"
        
    if status == "FOUND":
        # Lọc chunk theo fields
        doc_chunks = [c for c in raw_results if c.document_id == best_doc_id]
        final_chunks = _filter_chunks_by_fields(doc_chunks, sub_query.fields, top_k)
    else:
        final_chunks = []
        
    return SubResult(
        sub_query=sub_query,
        status=status,
        document_id=best_doc_id if status == "FOUND" else None,
        chunks=final_chunks,
        suggested_title=suggested_title,
        score=best_score
    )

def resolve_all(sub_queries: list[SubQuery], context: dict | None, domain: str) -> list[SubResult]:
    """
    Resolve a list of subqueries.
    TODO: Use batch embedding if supported, for now sequential.
    """
    return [resolve_sub_query(sq, context, domain) for sq in sub_queries]
