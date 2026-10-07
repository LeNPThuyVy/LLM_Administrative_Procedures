import os
import time
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    PayloadSchemaType,
)

load_dotenv()

DISTANCE_MAP = {
    "cosine": Distance.COSINE,
    "dot": Distance.DOT,
    "euclid": Distance.EUCLID,
}


class QdrantVectorStore:
    def __init__(self, config):
        self.config = config

        url = os.getenv("QDRANT_URL")
        api_key = os.getenv("QDRANT_API_KEY")

        if not url:
            raise RuntimeError("QDRANT_URL chưa được cấu hình trong .env")

        if not api_key:
            raise RuntimeError("QDRANT_API_KEY chưa được cấu hình trong .env")

        self.client = QdrantClient(
            url=url,
            api_key=api_key,
            timeout=60,
        )

    def ensure_collection(self) -> None:
        name = self.config.collection_name

        existing = [
            c.name
            for c in self.client.get_collections().collections
        ]

        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=self.config.embedding_dim,
                    distance=DISTANCE_MAP[self.config.distance_metric],
                ),
            )

            self.client.create_payload_index(
                collection_name=name,
                field_name="document_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )

            self.client.create_payload_index(
                collection_name=name,
                field_name="field",
                field_schema=PayloadSchemaType.KEYWORD,
            )

            print(f"[qdrant] Created collection: {name}")
            return

        info = self.client.get_collection(name)
        vector_config = info.config.params.vectors

        if vector_config.size != self.config.embedding_dim:
            raise ValueError(
                f"Collection '{name}' vector size mismatch: "
                f"{vector_config.size} != {self.config.embedding_dim}"
            )

        expected_distance = DISTANCE_MAP[self.config.distance_metric]

        if vector_config.distance != expected_distance:
            raise ValueError(
                f"Collection '{name}' distance mismatch: "
                f"{vector_config.distance} != {expected_distance}"
            )

        print(f"[qdrant] Collection OK: {name}")

    def upsert(
        self,
        chunks: list,
        embeddings: list[list[float]],
        batch_size: int = 50,
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks và embeddings phải có cùng số lượng")

        points = []

        for chunk, embedding in zip(chunks, embeddings):
            points.append(
                PointStruct(
                    id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_DNS,
                            chunk.chunk_id,
                        )
                    ),
                    vector=embedding,
                    payload={
                        **chunk.metadata,
                        "text": chunk.text,
                    },
                )
            )

        total = 0

        for start in range(0, len(points), batch_size):
            batch = points[start:start + batch_size]

            for attempt in range(1, 4):
                try:
                    self.client.upsert(
                        collection_name=self.config.collection_name,
                        points=batch,
                        wait=True,
                    )
                    total += len(batch)
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(attempt)

        return total

    def delete_collection(self) -> None:
        existing = [
            c.name
            for c in self.client.get_collections().collections
        ]

        if self.config.collection_name in existing:
            self.client.delete_collection(
                self.config.collection_name
            )
            print(
                f"[qdrant] Deleted collection: "
                f"{self.config.collection_name}"
            )

    def count(self) -> int:
        return self.client.count(
            self.config.collection_name
        ).count