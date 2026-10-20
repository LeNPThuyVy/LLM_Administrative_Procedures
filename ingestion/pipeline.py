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
        self.embedder = BGEEmbedder(self.config)
        self.store = QdrantVectorStore(self.config)
        self.deduplicator = SimilarityDeduplicator(
            self.config.dedup_threshold
        )
        self.tracker = VersionTracker()

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

        if force_reindex:
            self.store.delete_collection()

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
            f"[pipeline] Dedup removed: "
            f"{len(dedup_result.removed)}"
        )

        print(
            f"[time] dedup = {time.perf_counter() - t0:.2f}s"
        )

        # 4. CHUNK
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

        print(
            f"[pipeline] Chunks: {len(chunks)}"
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

        # 5. EMBED CHUNKS
        t0 = time.perf_counter()

        chunk_embeddings = self.embedder.encode(
            [chunk.text for chunk in chunks]
        )

        print(
            f"[time] embed = {time.perf_counter() - t0:.2f}s"
        )

        # 6. UPSERT
        t0 = time.perf_counter()

        upserted = self.store.upsert(
            chunks,
            chunk_embeddings,
        )

        print(
            f"[pipeline] Upserted: {upserted}"
        )

        print(
            f"[time] upsert = {time.perf_counter() - t0:.2f}s"
        )

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