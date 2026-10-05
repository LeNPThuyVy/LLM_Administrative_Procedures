# Baseline Evaluation Before Qdrant Migration

- Ngày thực hiện: 2026-10-05
- Môi trường: ChromaDB + sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

## Kết quả test/eval_fast.py Baseline

### Single-Turn Evaluation (Retrieval & Field Detection)
- Doc Hit@1: 19/20 (95.0%)
- Field Match: 19/20 (95.0%)

### Multi-Turn Evaluation (Follow-up Resolution)
- Multi-turn Pass: 6/8 (75.0%)
