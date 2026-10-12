import json
from pathlib import Path
from dataclasses import dataclass
import unicodedata
from typing import Optional

from domains.runtime import get_domain_runtime

@dataclass
class TitleEntry:
    document_id: str
    title: str
    aliases: list[str]

# Simple in-memory cache
_TITLE_INDEX: dict[str, list[TitleEntry]] = {}

def normalize_text(text: str) -> str:
    """Normalize text by lowercasing and removing diacritics."""
    text = text.lower()
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').strip()

def _build_index_for_domain(domain: str) -> list[TitleEntry]:
    runtime = get_domain_runtime(domain)
    config = runtime.config
    
    entries = []
    
    # Load from sources
    for source in config.sources:
        if source.get("type") == "json":
            # the path in config is usually relative to project root
            # or we need to find it relative to current working dir
            p = Path(source.get("path"))
            if not p.exists():
                p = Path(__file__).parent.parent.parent / p
            
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    for item in data:
                        doc_id = item.get("document_id")
                        title = item.get("title")
                        if doc_id and title:
                            # Build aliases
                            norm_title = normalize_text(title)
                            aliases = [norm_title, title.lower()]
                            
                            # Add keywords that match the title
                            for kw in config.entity_keywords:
                                if kw.lower() in title.lower():
                                    aliases.append(kw.lower())
                                    aliases.append(normalize_text(kw))
                            
                            entries.append(TitleEntry(
                                document_id=doc_id,
                                title=title,
                                aliases=list(set(aliases))
                            ))
                except Exception as e:
                    print(f"[title_index] Error loading {p}: {e}")

    return entries

def get_title_index(domain: Optional[str] = None) -> list[TitleEntry]:
    """Get or build the title index for the given domain."""
    runtime = get_domain_runtime(domain)
    domain_id = runtime.domain_id
    
    if domain_id not in _TITLE_INDEX:
        _TITLE_INDEX[domain_id] = _build_index_for_domain(domain_id)
        
    return _TITLE_INDEX[domain_id]

def find_procedures_in_text(text: str, domain: Optional[str] = None) -> list[TitleEntry]:
    """Find mentioned procedures by scanning the text for title aliases."""
    index = get_title_index(domain)
    norm_text = normalize_text(text)
    lower_text = text.lower()
    
    # Create a list of (alias, entry) sorted by alias length (longest first)
    all_aliases = []
    for entry in index:
        for alias in entry.aliases:
            all_aliases.append((alias, entry))
            
    all_aliases.sort(key=lambda x: len(x[0]), reverse=True)
    
    found = []
    seen_docs = set()
    
    # We will mask out parts of the string that are already matched to avoid overlaps
    masked_lower = lower_text
    masked_norm = norm_text
    
    for alias, entry in all_aliases:
        if entry.document_id in seen_docs:
            continue
            
        # Try finding in lower_text
        idx = masked_lower.find(alias)
        is_norm = False
        if idx == -1:
            idx = masked_norm.find(alias)
            is_norm = True
            
        if idx != -1:
            found.append(entry)
            seen_docs.add(entry.document_id)
            # Mask the matched part with spaces
            mask = ' ' * len(alias)
            # Mask BOTH to avoid double matching
            masked_lower = masked_lower[:idx] + mask + masked_lower[idx + len(alias):]
            masked_norm = masked_norm[:idx] + mask + masked_norm[idx + len(alias):]
                
    return found
