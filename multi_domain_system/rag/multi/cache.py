import hashlib
import json
from typing import Optional
from rag.multi.section import Section

# Simple in-memory cache for Sections
_SECTION_CACHE: dict[str, Section] = {}

def _generate_cache_key(document_id: str, fields: list[str]) -> str:
    fields_tuple = tuple(sorted(fields))
    raw_key = f"{document_id}:{fields_tuple}"
    return hashlib.md5(raw_key.encode('utf-8')).hexdigest()

def get_section_cache(document_id: str, fields: list[str]) -> Optional[Section]:
    key = _generate_cache_key(document_id, fields)
    return _SECTION_CACHE.get(key)

def set_section_cache(document_id: str, fields: list[str], section: Section) -> None:
    key = _generate_cache_key(document_id, fields)
    _SECTION_CACHE[key] = section
