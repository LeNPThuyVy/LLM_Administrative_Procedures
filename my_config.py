
from pathlib import Path 
import torch

BASE_DIR = Path(__file__).resolve().parent

PROCEDURES_PATH = BASE_DIR / "data" / "procedures.json"
CHROMA_PATH = BASE_DIR / "data" / "chroma_db"

COLLECTION_NAME = "procedures"

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200

DEFAULT_TOP_K = 3

MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"

MAX_NEW_TOKENS = 128
TEMPERATURE = 0.0
TOP_P = 0.9

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"