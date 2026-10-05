import os
from pathlib import Path 
import torch
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

PROCEDURES_PATH = BASE_DIR / "data" / "procedures.json"
CHROMA_PATH = BASE_DIR / "data" / "chroma_db"  # deprecated

# Qdrant Cloud & Vector Store Settings
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

DEFAULT_DOMAIN = "administrative_procedures"
DEFAULT_COLLECTION = os.getenv("DEFAULT_COLLECTION", "admin_dev")
COLLECTION_NAME = DEFAULT_COLLECTION

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200

DEFAULT_TOP_K = 5

MODEL_1_5B_PATH = Path(BASE_DIR / "model" / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
MODEL_3B_PATH = Path(BASE_DIR / "model" / "Qwen2.5-3B-Instruct-Q4_K_M.gguf")

# Default model path for RAG final answer generation
MODEL_PATH = MODEL_3B_PATH

MIN_RETRIEVAL_SCORE = 0.50

SUPPORTED_LOCATIONS = {
    "hồ chí minh", "hcm", "tp hcm", "tp.hcm", "thành phố hồ chí minh",
    "sài gòn", "saigon", "sg",
}

MODEL_NAME = "Qwen/Qwen2.5-0.5B-Instruct"

MAX_NEW_TOKENS = 512
TEMPERATURE = 0.0
TOP_P = 0.9

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

VAST_URL = "https://coast-relevance-november-everyone.trycloudflare.com"
