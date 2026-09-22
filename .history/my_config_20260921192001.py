from pathlib import Path 
import torch

BASE_DIR = Path(__file__).resolve().parent

PROCEDURES_PATH = BASE_DIR / "data" / "procedures.json"
CHROMA_PATH = BASE_DIR / "data" / "chroma_db"

COLLECTION_NAME = "procedures"

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200

DEFAULT_TOP_K = 3

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

VAST_URL = "https://modeling-wesley-display-likelihood.trycloudflare.com"
