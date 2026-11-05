import json
import math
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional

import httpx
import my_config as cfg


def fold_vietnamese(text: str) -> str:
    """
    Chuẩn hóa văn bản tiếng Việt sang chữ thường và loại bỏ dấu tiếng Việt (ASCII folding).
    Ví dụ: 'Phở bò tái lăn' -> 'pho bo tai lan'
    """
    if not text:
        return ""
    text = text.lower()
    # Chuyển ký tự đặc biệt tiếng Việt: đ/Đ -> d
    text = text.replace("đ", "d").replace("Đ", "d")
    # Decompose unicode và lọc các combining diacritics
    nfd = unicodedata.normalize("NFD", text)
    cleaned = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", cleaned)


def tokenize_text(text: str) -> list[str]:
    """Tách từ đơn giản cho tiếng Việt / Unicode."""
    if not text:
        return []
    words = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
    return [w for w in words if len(w) > 0]


class LocalBM25Engine:
    """
    Bộ máy Okapi BM25 đa trường nội bộ (Inverted Index) chạy trên đĩa/RAM.
    Được kích hoạt tự động làm fallback khi Elasticsearch Server (port 9200) chưa bật.
    Hỗ trợ tính điểm Okapi BM25 đa trường và Vietnamese ASCII Folding.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b

    def search(
        self,
        docs: list[dict],
        query: str,
        top_k: int = 15,
    ) -> list[dict]:
        if not docs or not query or not query.strip():
            return []

        q_clean = query.strip().lower()
        q_folded = fold_vietnamese(q_clean)

        query_tokens_raw = tokenize_text(q_clean)
        query_tokens_folded = tokenize_text(q_folded)
        all_query_terms = list(set(query_tokens_raw + query_tokens_folded))

        if not all_query_terms:
            return []

        N = len(docs)
        # 1. Tính Document Frequency (DF) cho từng term
        df: dict[str, int] = {}
        doc_lengths: list[float] = []
        doc_tokens_list: list[dict[str, Any]] = []

        for d in docs:
            title = str(d.get("title", "")).lower()
            title_folded = fold_vietnamese(title)
            aliases = " ".join([str(a).lower() for a in d.get("aliases", [])])
            aliases_folded = fold_vietnamese(aliases)
            category = str(d.get("category", "")).lower()
            category_folded = fold_vietnamese(category)
            text = str(d.get("text", "")).lower()
            text_folded = fold_vietnamese(text)

            t_tokens = tokenize_text(title) + tokenize_text(title_folded)
            a_tokens = tokenize_text(aliases) + tokenize_text(aliases_folded)
            c_tokens = tokenize_text(category) + tokenize_text(category_folded)
            txt_tokens = tokenize_text(text) + tokenize_text(text_folded)

            doc_len = len(t_tokens) * 3.5 + len(a_tokens) * 2.5 + len(c_tokens) * 1.5 + len(txt_tokens) * 1.0
            doc_lengths.append(doc_len)

            unique_doc_terms = set(t_tokens + a_tokens + c_tokens + txt_tokens)
            for term in unique_doc_terms:
                df[term] = df.get(term, 0) + 1

            doc_tokens_list.append({
                "t_tokens": t_tokens,
                "a_tokens": a_tokens,
                "c_tokens": c_tokens,
                "txt_tokens": txt_tokens,
                "title_raw": title,
                "title_folded": title_folded,
                "text_raw": text,
                "text_folded": text_folded,
            })

        avg_dl = sum(doc_lengths) / max(N, 1)

        # 2. Tính BM25 Score cho từng document
        scored_docs = []
        for idx, (d, dt) in enumerate(zip(docs, doc_tokens_list)):
            dl = doc_lengths[idx]
            score = 0.0

            # Tính tần suất từ (Term Frequency) theo từng trường
            tf_title: dict[str, int] = {}
            for t in dt["t_tokens"]:
                tf_title[t] = tf_title.get(t, 0) + 1

            tf_aliases: dict[str, int] = {}
            for a in dt["a_tokens"]:
                tf_aliases[a] = tf_aliases.get(a, 0) + 1

            tf_category: dict[str, int] = {}
            for c in dt["c_tokens"]:
                tf_category[c] = tf_category.get(c, 0) + 1

            tf_text: dict[str, int] = {}
            for txt in dt["txt_tokens"]:
                tf_text[txt] = tf_text.get(txt, 0) + 1

            for term in all_query_terms:
                term_df = df.get(term, 0)
                if term_df == 0:
                    continue

                # IDF chuẩn Okapi
                idf = math.log(1.0 + (N - term_df + 0.5) / (term_df + 0.5))
                if idf <= 0:
                    idf = 0.05

                # Tổng TF có trọng số giữa các trường
                weighted_tf = (
                    tf_title.get(term, 0) * 3.5
                    + tf_aliases.get(term, 0) * 2.5
                    + tf_category.get(term, 0) * 1.5
                    + tf_text.get(term, 0) * 1.0
                )

                if weighted_tf > 0:
                    # Công thức Okapi BM25 TF-component
                    tf_norm = (weighted_tf * (self.k1 + 1.0)) / (
                        weighted_tf + self.k1 * (1.0 - self.b + self.b * (dl / max(avg_dl, 1.0)))
                    )
                    score += idf * tf_norm

            # Bonus cụm từ liên tiếp (Exact phrase bonus)
            if q_clean and (q_clean in dt["title_raw"] or q_folded in dt["title_folded"]):
                score += 3.0
            if q_clean and (q_clean in dt["text_raw"] or q_folded in dt["text_folded"]):
                score += 1.2

            if score > 0:
                # Chuẩn hóa về thang [0.0, 1.0] tương thích với min_retrieval_score
                normalized_score = score / (score + 4.0)
                scored_docs.append({
                    "doc": d,
                    "score": round(normalized_score, 4),
                    "raw_score": round(score, 4),
                })

        # Sắp xếp điểm cao nhất trước
        scored_docs.sort(key=lambda x: x["score"], reverse=True)
        return scored_docs[:top_k]


# In-memory index cache để tìm kiếm < 1ms
_LOCAL_INDEX_CACHE: dict[str, list[dict]] = {}
_ES_AVAILABILITY_CACHE: dict[str, tuple[bool, float]] = {}


class ElasticTabularStore:
    """
    Tầng Lưu trữ & Tìm kiếm Elasticsearch chuyên dụng cho dữ liệu dạng bảng (Excel / CSV).
    - Tầng 1: Elasticsearch Server qua HTTP API (http://127.0.0.1:9200)
    - Tầng 2: Local Okapi BM25 Engine fallback (data/elastic_local/{collection_name}.json)
    """

    def __init__(self, config: Any):
        self.config = config
        self.collection_name = getattr(config, "collection_name", None) or getattr(config, "domain_id", "default")
        self.es_url = cfg.ELASTICSEARCH_URL.rstrip("/")
        self.api_key = cfg.ELASTICSEARCH_API_KEY
        self.local_dir = cfg.ELASTIC_LOCAL_DIR
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.local_file = self.local_dir / f"{self.collection_name}.json"
        self.bm25 = LocalBM25Engine()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    def is_es_server_available(self) -> bool:
        """Kiểm tra nhanh xem Elasticsearch Server có đang chạy tại port 9200 không (cache 15s)."""
        now = time.time()
        cached = _ES_AVAILABILITY_CACHE.get(self.es_url)
        if cached and (now - cached[1] < 15.0):
            return cached[0]

        try:
            with httpx.Client(timeout=1.0) as client:
                res = client.get(self.es_url, headers=self._headers())
                is_ok = res.status_code == 200
                _ES_AVAILABILITY_CACHE[self.es_url] = (is_ok, now)
                return is_ok
        except Exception:
            _ES_AVAILABILITY_CACHE[self.es_url] = (False, now)
            return False

    def ensure_collection(self) -> None:
        """Khởi tạo collection trên Elasticsearch Server và thư mục local fallback."""
        self.local_dir.mkdir(parents=True, exist_ok=True)

        if not self.is_es_server_available():
            print(f"[elastic_store][{self.collection_name}] ES Server offline, using Local BM25 Store at {self.local_file}")
            return

        try:
            with httpx.Client(timeout=5.0) as client:
                # Kiểm tra index đã tồn tại chưa
                chk = client.head(f"{self.es_url}/{self.collection_name}", headers=self._headers())
                if chk.status_code == 200:
                    print(f"[elastic_store][{self.collection_name}] ES Server index OK")
                    return

                # Tạo mới index với custom analyzer tiếng Việt (lowercase + asciifolding)
                mapping_payload = {
                    "settings": {
                        "analysis": {
                            "analyzer": {
                                "vn_folded": {
                                    "tokenizer": "standard",
                                    "filter": ["lowercase", "asciifolding"],
                                }
                            }
                        }
                    },
                    "mappings": {
                        "properties": {
                            "chunk_id": {"type": "keyword"},
                            "document_id": {"type": "keyword"},
                            "title": {
                                "type": "text",
                                "analyzer": "vn_folded",
                                "fields": {"keyword": {"type": "keyword"}},
                            },
                            "category": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword"}},
                            },
                            "aliases": {
                                "type": "text",
                                "analyzer": "vn_folded",
                            },
                            "text": {
                                "type": "text",
                                "analyzer": "vn_folded",
                            },
                            "metadata": {
                                "type": "object",
                                "enabled": True,
                            },
                        }
                    },
                }
                res = client.put(f"{self.es_url}/{self.collection_name}", headers=self._headers(), json=mapping_payload)
                if res.status_code in (200, 201):
                    print(f"[elastic_store][{self.collection_name}] Created ES index with vn_folded analyzer")
                else:
                    print(f"[elastic_store][{self.collection_name}] Create index notice: {res.status_code} {res.text}")
        except Exception as e:
            print(f"[elastic_store][{self.collection_name}] Error ensuring ES index: {e}")

    def _load_local_docs(self) -> list[dict]:
        """Tải dữ liệu từ cache hoặc file JSON local."""
        if self.collection_name in _LOCAL_INDEX_CACHE:
            return _LOCAL_INDEX_CACHE[self.collection_name]

        if self.local_file.exists():
            try:
                docs = json.loads(self.local_file.read_text(encoding="utf-8"))
                _LOCAL_INDEX_CACHE[self.collection_name] = docs
                return docs
            except Exception as e:
                print(f"[elastic_store] Error loading local file: {e}")
        return []

    def _save_local_docs(self, docs: list[dict]):
        """Lưu dữ liệu bền vững xuống file JSON local và bộ nhớ RAM."""
        _LOCAL_INDEX_CACHE[self.collection_name] = docs
        try:
            self.local_file.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[elastic_store] Error saving local file: {e}")

    def upsert(self, chunks: list[Any]) -> int:
        """
        Nạp toàn bộ chunks dạng bảng vào Elasticsearch và Local Fallback Store.
        LƯU Ý: Không nhận vector embeddings! Tốc độ nạp siêu tốc.
        """
        if not chunks:
            return 0

        documents = []
        for chunk in chunks:
            meta = getattr(chunk, "metadata", {}) or {}
            doc_id = meta.get("document_id") or ""
            title = meta.get("title") or ""
            category = meta.get("category") or "chung"
            aliases = meta.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(",") if a.strip()]

            doc_record = {
                "chunk_id": str(getattr(chunk, "chunk_id", "")),
                "document_id": str(doc_id),
                "title": str(title),
                "category": str(category),
                "aliases": list(aliases),
                "text": str(getattr(chunk, "text", "")),
                "metadata": {
                    **meta,
                    "chunk_id": getattr(chunk, "chunk_id", ""),
                    "text": getattr(chunk, "text", ""),
                },
            }
            documents.append(doc_record)

        # 1. Luôn lưu bản sao vào Local Fallback Store (0.01s)
        self._save_local_docs(documents)

        # 2. Đẩy lên Elasticsearch Server nếu khả dụng
        if self.is_es_server_available():
            try:
                self.ensure_collection()
                # Tạo NDJSON cho Bulk API
                lines = []
                for d in documents:
                    action = {"index": {"_index": self.collection_name, "_id": d["chunk_id"]}}
                    lines.append(json.dumps(action, ensure_ascii=False))
                    lines.append(json.dumps(d, ensure_ascii=False))
                bulk_body = "\n".join(lines) + "\n"

                with httpx.Client(timeout=30.0) as client:
                    headers = {"Content-Type": "application/x-ndjson"}
                    if self.api_key:
                        headers["Authorization"] = f"ApiKey {self.api_key}"
                    res = client.post(f"{self.es_url}/_bulk?refresh=true", headers=headers, content=bulk_body.encode("utf-8"))
                    if res.status_code in (200, 201):
                        resp_json = res.json()
                        errors = resp_json.get("errors", False)
                        if not errors:
                            print(f"[elastic_store][{self.collection_name}] Successfully indexed {len(documents)} docs into ES Server")
                        else:
                            print(f"[elastic_store][{self.collection_name}] Bulk index completed with partial item notes")
            except Exception as e:
                print(f"[elastic_store][{self.collection_name}] Note: Bulk push to ES Server failed ({e}), local fallback is ready")

        return len(documents)

    def search(self, query: str, top_k: int = 15) -> list[dict]:
        """
        Tìm kiếm thông tin theo BM25 đa trường.
        Trả về danh sách dict có cấu trúc tương thích với ScoredPoint của Qdrant:
        [{"id": chunk_id, "score": normalized_score, "payload": {...}}, ...]
        """
        if not query or not query.strip():
            return []

        # 1. Thử tìm kiếm trên Elasticsearch Server trước
        if self.is_es_server_available():
            try:
                search_payload = {
                    "size": top_k,
                    "query": {
                        "bool": {
                            "should": [
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": ["title^3.5", "aliases^2.5", "category^1.5", "text^1.0"],
                                        "type": "best_fields",
                                        "fuzziness": "AUTO",
                                    }
                                },
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": ["title^4.0", "aliases^3.0", "text^1.5"],
                                        "type": "phrase",
                                    }
                                },
                            ]
                        }
                    },
                }
                with httpx.Client(timeout=2.0) as client:
                    res = client.post(
                        f"{self.es_url}/{self.collection_name}/_search",
                        headers=self._headers(),
                        json=search_payload,
                    )
                    if res.status_code == 200:
                        hits_data = res.json().get("hits", {}).get("hits", [])
                        results = []
                        for h in hits_data:
                            src = h.get("_source", {})
                            raw_score = float(h.get("_score") or 0.0)
                            # Chuẩn hóa BM25 raw score về dải [0.0, 1.0]
                            normalized_score = raw_score / (raw_score + 4.0)
                            payload = src.get("metadata") or {
                                "chunk_id": src.get("chunk_id"),
                                "document_id": src.get("document_id"),
                                "title": src.get("title"),
                                "category": src.get("category"),
                                "aliases": src.get("aliases"),
                                "text": src.get("text"),
                            }
                            results.append({
                                "id": src.get("chunk_id", h.get("_id")),
                                "score": round(normalized_score, 4),
                                "payload": payload,
                            })
                        if results:
                            return results
            except Exception as e:
                print(f"[elastic_store] ES Server search error ({e}), switching to Local BM25 fallback")

        # 2. Fallback sang Local BM25 Engine
        docs = self._load_local_docs()
        bm25_matches = self.bm25.search(docs=docs, query=query, top_k=top_k)
        results = []
        for m in bm25_matches:
            doc = m["doc"]
            payload = doc.get("metadata") or {
                "chunk_id": doc.get("chunk_id"),
                "document_id": doc.get("document_id"),
                "title": doc.get("title"),
                "category": doc.get("category"),
                "aliases": doc.get("aliases"),
                "text": doc.get("text"),
            }
            results.append({
                "id": doc.get("chunk_id"),
                "score": m["score"],
                "payload": payload,
            })
        return results

    def delete_collection(self) -> None:
        """Xóa collection trên cả Elasticsearch Server và file local."""
        if self.is_es_server_available():
            try:
                with httpx.Client(timeout=5.0) as client:
                    client.delete(f"{self.es_url}/{self.collection_name}", headers=self._headers())
                    print(f"[elastic_store][{self.collection_name}] Deleted ES index on server")
            except Exception as e:
                print(f"[elastic_store] Warning deleting ES index: {e}")

        _LOCAL_INDEX_CACHE.pop(self.collection_name, None)
        if self.local_file.exists():
            try:
                self.local_file.unlink()
                print(f"[elastic_store][{self.collection_name}] Deleted local BM25 file {self.local_file}")
            except Exception as e:
                print(f"[elastic_store] Warning deleting local file: {e}")

    def count(self) -> int:
        """Trả về số lượng bản ghi trong index."""
        if self.is_es_server_available():
            try:
                with httpx.Client(timeout=2.0) as client:
                    res = client.get(f"{self.es_url}/{self.collection_name}/_count", headers=self._headers())
                    if res.status_code == 200:
                        return int(res.json().get("count", 0))
            except Exception:
                pass
        return len(self._load_local_docs())
