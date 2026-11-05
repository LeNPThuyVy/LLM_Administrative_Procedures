import pytest
import os
import uuid
import my_config as cfg
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

def test_qdrant_cloud_connection():
    assert cfg.QDRANT_URL, "QDRANT_URL must be configured in .env"
    client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY or None)
    
    # Test getting collections list
    collections = client.get_collections()
    assert collections is not None

def test_qdrant_temp_collection_lifecycle():
    if not cfg.QDRANT_URL:
        pytest.skip("QDRANT_URL is not set")
        
    client = QdrantClient(url=cfg.QDRANT_URL, api_key=cfg.QDRANT_API_KEY or None)
    test_collection = f"test_tang1_temp_{uuid.uuid4().hex[:8]}"
    
    try:
        # Create temp collection
        client.create_collection(
            collection_name=test_collection,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
        )
        
        # Verify collection exists
        info = client.get_collection(test_collection)
        assert info.points_count == 0
        assert info.config.params.vectors.size == 1024
        
        # Upsert dummy point
        dummy_vector = [0.1] * 1024
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "test_chunk_001"))
        client.upsert(
            collection_name=test_collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=dummy_vector,
                    payload={"title": "Test Point", "document_id": "TEST_DOC_1"}
                )
            ]
        )
        
        # Check count
        count = client.count(test_collection).count
        assert count == 1
        
        # Query points
        query_res = client.query_points(
            collection_name=test_collection,
            query=dummy_vector,
            limit=1
        )
        points = query_res.points if hasattr(query_res, "points") else query_res
        assert len(points) == 1
        assert points[0].payload["document_id"] == "TEST_DOC_1"
        
    finally:
        # Cleanup temp collection
        existing = [c.name for c in client.get_collections().collections]
        if test_collection in existing:
            client.delete_collection(test_collection)
