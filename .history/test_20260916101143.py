from rag.procedure_reader import procedure_reader
from rag.retrieval import RetrievedChunk


results = procedure_reader(
    "đăng ký hộ kinh doanh",
    None,
    top_k=2,
)

assert isinstance(results, list)
assert len(results) <= 2
assert all(isinstance(chunk, RetrievedChunk) for chunk in results)

print(results)
print("Test passed!")