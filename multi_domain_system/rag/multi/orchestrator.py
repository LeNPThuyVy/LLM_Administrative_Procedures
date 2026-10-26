import asyncio
import time
from typing import AsyncGenerator

from rag.multi.detector import detect_sub_queries
from rag.multi.resolver import resolve_all
from rag.multi.section import build_section_llm, build_section_template
from rag.mapper import AnswerResponse
import my_config as cfg

async def answer_multi_stream(
    query: str,
    context: dict | None = None,
    domain: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Luồng trả lời đa ý định qua SSE.
    """
    domain = domain or cfg.DEFAULT_DOMAIN
    
    # 1. Detector
    sub_queries, truncated = detect_sub_queries(query, context or {}, domain)
    
    # 2. Resolve (vector search for each)
    # TODO: This blocks the event loop briefly. Use to_thread if needed, but it's fast.
    sub_results = await asyncio.to_thread(resolve_all, sub_queries, context, domain)
    
    # 3. Phân loại plan
    found_titles = []
    missing_titles = []
    
    for res in sub_results:
        title = res.suggested_title or res.sub_query.raw_mention
        if res.status == "FOUND":
            found_titles.append(title)
        else:
            missing_titles.append(title)
            
    # Gửi plan
    yield {
        "event": "plan",
        "data": {
            "found": found_titles,
            "missing": missing_titles,
            "truncated": truncated
        }
    }
    
    # 4. Build từng section và yield
    sections = []
    evidence_start_index = 1
    for res in sub_results:
        # Build section (LLM or template)
        # TODO: Implement concurrency limit via semaphore if using LLM
        # For now, just use template which is very fast
        section = await asyncio.to_thread(build_section_template, res, evidence_start_index)
        sections.append(section)
        evidence_start_index += len(res.chunks)
        
        # Yield section immediately
        yield {
            "event": "section",
            "data": {
                "order": section.order,
                "title": section.title,
                "status": section.status,
                "text": section.text,
                "evidence_list": [
                    {
                        "document_id": c.document_id,
                        "title": c.title,
                        "chunk_id": c.chunk_id
                    }
                    for c in section.claims
                ] if section.claims else []
            }
        }
        
    yield {
        "event": "done",
        "data": "done"
    }
