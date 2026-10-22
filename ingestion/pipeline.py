from dataclasses import dataclass
from pathlib import Path
import importlib
import time

from pydantic import BaseModel

from domains.domain_loader import load_domain_config
from ingestion.loaders import get_loader
from ingestion.schema_validator import validate_documents
from ingestion.chunker import FieldChunker

from ingestion.embedder import BGEEmbedder
from ingestion.elastic_store import ElasticTabularStore
from ingestion.dedup import SimilarityDeduplicator
from ingestion.vector_store import QdrantVectorStore
from ingestion.version_tracker import VersionTracker


@dataclass
class IngestionResult:
    domain_id: str
    total_loaded: int
    total_valid: int
    total_after_dedup: int
    total_chunks: int
    removed_duplicates: list
    validation_errors: list


class IngestionPipeline:
    def __init__(self, domain_id: str):
        self.domain_id = domain_id
        self.config = load_domain_config(domain_id)

        self.chunker = FieldChunker(self.config)
        self._embedder = None
        self.elastic_store = ElasticTabularStore(self.config)
        self.store = QdrantVectorStore(self.config)
        self.deduplicator = SimilarityDeduplicator(
            self.config.dedup_threshold
        )
        self.tracker = VersionTracker()

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = BGEEmbedder(self.config)
        return self._embedder

    def _load_schema(self):
        try:
            module = importlib.import_module(
                f"domains.{self.domain_id}.schema"
            )

            for name in dir(module):
                obj = getattr(module, name)

                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseModel)
                    and obj is not BaseModel
                ):
                    return obj
        except Exception as e:
            print(f"[pipeline][{self.domain_id}] Schema module note ({e}), using GenericDomainDocument fallback")

        from pydantic import ConfigDict
        from typing import Optional

        class GenericDomainDocument(BaseModel):
            model_config = ConfigDict(extra="allow")

            document_id: str
            title: str
            category: str = "chung"
            content: Optional[str] = None
            source_url: Optional[str] = None
            aliases: list[str] = []

        return GenericDomainDocument

    def _source_paths(self):
        paths = []

        for source in self.config.sources:
            raw_path = source.get("path")

            if raw_path:
                paths.append(Path(raw_path))

        return paths

    def _has_changes(self) -> bool:
        paths = self._source_paths()

        if not paths:
            return True

        return any(
            self.tracker.has_changed(self.domain_id, path)
            for path in paths
        )

    def _mark_sources_indexed(self):
        for path in self._source_paths():
            self.tracker.mark_indexed(
                self.domain_id,
                path,
            )

    def run(self, force_reindex: bool = False) -> IngestionResult:
        started = time.perf_counter()

        if not force_reindex and not self._has_changes():
            print(
                f"[pipeline][{self.domain_id}] "
                "Không có thay đổi, bỏ qua re-index."
            )

            return IngestionResult(
                domain_id=self.domain_id,
                total_loaded=0,
                total_valid=0,
                total_after_dedup=0,
                total_chunks=0,
                removed_duplicates=[],
                validation_errors=[],
            )

        schema_cls = self._load_schema()

        use_elastic_tabular = (
            getattr(self.config, "search_backend", "") == "elasticsearch"
            or any(src.get("type") in ("csv", "xlsx") for src in self.config.sources)
        )

        if force_reindex:
            if use_elastic_tabular:
                self.elastic_store.delete_collection()
            else:
                self.store.delete_collection()

        if use_elastic_tabular:
            self.elastic_store.ensure_collection()
        else:
            self.store.ensure_collection()

        # 1. LOAD
        t0 = time.perf_counter()

        all_raw = []

        for source_cfg in self.config.sources:
            loader = get_loader(source_cfg["type"])
            raw_docs = loader.load(source_cfg)
            all_raw.extend(raw_docs)

            print(
                f"[pipeline][{self.domain_id}] "
                f"Loaded {len(raw_docs)} docs "
                f"from {source_cfg['type']}"
            )

        print(
            f"[time] load = {time.perf_counter() - t0:.2f}s"
        )

        # AI CHUNK PLANNING & COLUMN MAPPING
        column_mapping = {}
        try:
            from ingestion.ai_chunk_planner import AIChunkPlanner
            planner = AIChunkPlanner(self.config)
            plan = planner.create_plan(all_raw)
            column_mapping = plan.get("column_mapping", {})
            self.chunker = FieldChunker(self.config)
        except Exception as e:
            print(f"[pipeline][{self.domain_id}] AI Chunk Planner note ({e}), using default mapping")

        # 2. VALIDATE
        t0 = time.perf_counter()

        valid_docs, validation_errors = validate_documents(
            all_raw,
            schema_cls,
            column_mapping=column_mapping,
        )

        print(
            f"[pipeline] Valid: "
            f"{len(valid_docs)}/{len(all_raw)}"
        )

        print(
            f"[time] validate = {time.perf_counter() - t0:.2f}s"
        )

        # 3. DEDUP
        t0 = time.perf_counter()

        # Kiểm tra xem nguồn dữ liệu nạp vào có phải dạng Tabular (Excel / CSV / Structured JSON) hay không
        is_all_tabular = False
        if any(src.get("type") in ("csv", "xlsx", "json") for src in self.config.sources):
            is_all_tabular = True
        elif valid_docs and all(
            getattr(doc, "source_type", "") == "tabular"
            or (hasattr(doc, "model_extra") and doc.model_extra and doc.model_extra.get("source_type") == "tabular")
            for doc in valid_docs
        ):
            is_all_tabular = True

        if is_all_tabular:
            # Nhánh Tabular: Khử trùng lặp siêu tốc theo document_id và hash nội dung (0.001s, không cần chạy BGE-M3 2 lần)
            seen_ids = set()
            seen_hashes = set()
            kept_docs = []
            removed_docs = []

            for doc in valid_docs:
                d_id = getattr(doc, "document_id", "")
                content_str = (getattr(doc, "title", "") + "||" + str(getattr(doc, "content", ""))).strip().lower()
                c_hash = hash(content_str)

                if (d_id and d_id in seen_ids) or (c_hash in seen_hashes):
                    removed_docs.append({
                        "removed_id": d_id,
                        "reason": "exact_duplicate_or_id_conflict"
                    })
                else:
                    if d_id:
                        seen_ids.add(d_id)
                    seen_hashes.add(c_hash)
                    kept_docs.append(doc)

            from ingestion.dedup import DedupResult
            dedup_result = DedupResult(kept=kept_docs, removed=removed_docs)
            print(f"[pipeline] Tabular Fast Dedup (Hash/ID): removed={len(removed_docs)}, kept={len(kept_docs)}")
        else:
            # Nhánh Unstructured Document: Sử dụng Vector Cosine Similarity
            representative_texts = [
                (
                    f"{getattr(doc, 'title', '')}\n{getattr(doc, 'content', '')}".strip()
                    or getattr(doc, "title", "")
                    or getattr(doc, "content", "")
                    or ""
                )
                for doc in valid_docs
            ]

            dedup_embeddings = self.embedder.encode(
                representative_texts
            )

            dedup_result = self.deduplicator.deduplicate(
                valid_docs,
                dedup_embeddings,
            )

            print(
                f"[pipeline] Vector Dedup removed: "
                f"{len(dedup_result.removed)}"
            )

        print(
            f"[time] dedup = {time.perf_counter() - t0:.2f}s"
        )

        # 4. CHUNK / FORMAT RECORD
        t0 = time.perf_counter()

        chunks = []

        for doc in dedup_result.kept:
            chunks.extend(
                self.chunker.chunk(doc)
            )

        chunks = [
            chunk
            for chunk in chunks
            if chunk.text.strip()
        ]

        if is_all_tabular:
            print(
                f"[pipeline] Tabular Records: {len(chunks)} records (1 row = 1 schema record, no sub-chunking)"
            )
        else:
            print(
                f"[pipeline] Document Chunks: {len(chunks)}"
            )

        print(
            f"[time] chunk = {time.perf_counter() - t0:.2f}s"
        )

        if not chunks:
            print(f"[pipeline][{self.domain_id}] Không sinh được chunk nào, bỏ qua embed & upsert.")
            return IngestionResult(
                domain_id=self.domain_id,
                total_loaded=len(all_raw),
                total_valid=len(valid_docs),
                total_after_dedup=len(dedup_result.kept),
                total_chunks=0,
                removed_duplicates=dedup_result.removed,
                validation_errors=validation_errors,
            )

        if use_elastic_tabular:
            # 5. BYPASS EMBEDDING CHO DỮ LIỆU BẢNG (EXCEL / CSV)
            print("[pipeline] Tabular Elasticsearch mode: Bỏ qua hoàn toàn bước Embedding (0.00s)")
            print("[time] embed = 0.00s (bypassed)")

            # 6. UPSERT VÀO ELASTICSEARCH / LOCAL BM25 STORE
            t0 = time.perf_counter()
            upserted = self.elastic_store.upsert(chunks)
            print(f"[pipeline] Upserted to ElasticTabularStore: {upserted}")
            print(f"[time] upsert = {time.perf_counter() - t0:.2f}s")
        else:
            # 5. EMBED CHUNKS (Dành cho PDF / DOCX / Legacy JSON)
            t0 = time.perf_counter()
            chunk_embeddings = self.embedder.encode(
                [chunk.text for chunk in chunks]
            )
            print(f"[time] embed = {time.perf_counter() - t0:.2f}s")

            # 6. UPSERT
            t0 = time.perf_counter()
            upserted = self.store.upsert(
                chunks,
                chunk_embeddings,
            )
            print(f"[pipeline] Upserted: {upserted}")
            print(f"[time] upsert = {time.perf_counter() - t0:.2f}s")

        # Chỉ mark sau khi upsert thành công ít nhất 1 chunk
        if upserted > 0:
            self._mark_sources_indexed()

        print(
            f"[pipeline] Total time: "
            f"{time.perf_counter() - started:.2f}s"
        )

        return IngestionResult(
            domain_id=self.domain_id,
            total_loaded=len(all_raw),
            total_valid=len(valid_docs),
            total_after_dedup=len(dedup_result.kept),
            total_chunks=upserted,
            removed_duplicates=dedup_result.removed,
            validation_errors=validation_errors,
        )
