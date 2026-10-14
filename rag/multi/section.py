from dataclasses import dataclass
from rag.multi.types import SubResult
from rag.pipeline import _answer_from_evidence
import my_config as cfg

@dataclass
class Section:
    order: int
    title: str | None
    status: str                 # FOUND | AMBIGUOUS | NOT_FOUND | ERROR
    text: str
    claims: list
    used_llm: bool

def build_section_template(sub_result: SubResult, evidence_start_index: int = 1) -> Section:
    """Builds section text using templates (without LLM)"""
    if sub_result.status == "FOUND" and sub_result.document_id:
        from rag.multi.cache import get_section_cache, set_section_cache
        cached = get_section_cache(sub_result.document_id, sub_result.sub_query.fields)
        if cached:
            # Update order since order might change per query
            cached.order = sub_result.sub_query.order
            return cached
            
        # Extract evidence text
        from rag.evidence_builder import build_evidence_candidates
        from rag.mapper import VerifiedClaim, Citation
        
        evidence_candidates = build_evidence_candidates(sub_result.chunks)
        # Shift candidate_ids to avoid overlap between sections if needed?
        # Actually it's fine if they restart at EC_001 since UI handles it per section,
        # but to be safe we could shift them by evidence_start_index.
        for i, ec in enumerate(evidence_candidates):
            ec.candidate_id = f"EC_{evidence_start_index + i:03d}"
            
        text = _answer_from_evidence(evidence_candidates, sub_result.sub_query.fields)
        
        # Build dummy verified claims to support citation chip in UI
        dummy_claims = []
        for ec in evidence_candidates:
            if f"[{ec.candidate_id}]" in text:
                dummy_claims.append(VerifiedClaim(
                    claim="",
                    status="SUPPORTED",
                    reason="Trích xuất trực tiếp từ tài liệu.",
                    citations=[Citation(
                        evidence_id=ec.candidate_id,
                        document_id=ec.document_id,
                        chunk_id=ec.chunk_id,
                        title=ec.title,
                        source_url=ec.source_url
                    )]
                ))
                
        section = Section(
            order=sub_result.sub_query.order,
            title=sub_result.suggested_title or sub_result.sub_query.procedure_hint,
            status="FOUND",
            text=text,
            claims=dummy_claims,  # UI needs this for citation mapping
            used_llm=False
        )
        set_section_cache(sub_result.document_id, sub_result.sub_query.fields, section)
        return section
    elif sub_result.status == "AMBIGUOUS":
        text = f"Câu hỏi của bạn về '{sub_result.sub_query.raw_mention}' có vẻ tương tự với nhiều thủ tục khác nhau. Vui lòng làm rõ tên thủ tục."
        return Section(
            order=sub_result.sub_query.order,
            title=sub_result.sub_query.raw_mention,
            status="AMBIGUOUS",
            text=text,
            claims=[],
            used_llm=False
        )
    else:
        title = sub_result.suggested_title or sub_result.sub_query.raw_mention
        text = "Hiện mình chưa có thông tin về thủ tục này trong dữ liệu."
        return Section(
            order=sub_result.sub_query.order,
            title=title,
            status="NOT_FOUND",
            text=text,
            claims=[],
            used_llm=False
        )

def build_section_llm(sub_result: SubResult, context: dict) -> Section:
    """Builds section text using LLM."""
    if sub_result.status != "FOUND":
        return build_section_template(sub_result)
        
    # TODO: Implement mini-RAG with generate_answer_3b
    # For now, fallback to template
    return build_section_template(sub_result)
