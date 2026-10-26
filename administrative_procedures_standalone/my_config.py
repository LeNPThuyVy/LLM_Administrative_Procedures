import os
from pathlib import Path 
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env inside standalone directory
if (BASE_DIR / ".env").exists():
    load_dotenv(BASE_DIR / ".env")

PROCEDURES_PATH = BASE_DIR / "data" / "procedures.json"
CHROMA_PATH = BASE_DIR / "data" / "chroma_db"  # deprecated

# Qdrant Cloud & Vector Store Settings
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

DEFAULT_DOMAIN = "administrative_procedures"
DEFAULT_COLLECTION = os.getenv("DEFAULT_COLLECTION", "administrative_procedures")
COLLECTION_NAME = DEFAULT_COLLECTION

EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200

DEFAULT_TOP_K = 5

# Models: Standalone model folder or MODEL_DIR env override
DEFAULT_MODEL_DIR = BASE_DIR / "model"
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(DEFAULT_MODEL_DIR)))

MODEL_1_5B_PATH = Path(os.getenv("LLM_1_5B_MODEL_PATH", str(MODEL_DIR / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")))
MODEL_3B_PATH = Path(os.getenv("LLM_3B_MODEL_PATH", str(MODEL_DIR / "Qwen2.5-3B-Instruct-Q4_K_M.gguf")))

# Default model path for RAG final answer generation
MODEL_PATH = MODEL_3B_PATH

# Llama-server performance optimization configuration
LLAMA_THREADS = int(os.getenv("LLAMA_THREADS", "4"))
LLAMA_PARALLEL = int(os.getenv("LLAMA_PARALLEL", "1"))
LLAMA_CTX_SIZE = int(os.getenv("LLAMA_CTX_SIZE", "4096"))
LLAMA_BATCH_SIZE = int(os.getenv("LLAMA_BATCH_SIZE", "512"))
LLAMA_UBATCH_SIZE = int(os.getenv("LLAMA_UBATCH_SIZE", "512"))

# Synthesizer optimization mode: 'rule' (default, bypass LLM with active procedure), 'llm', 'off'
SYNTHESIZER_MODE = os.getenv("SYNTHESIZER_MODE", "rule").lower()

MIN_RETRIEVAL_SCORE = 0.50

SUPPORTED_LOCATIONS = {
    "hồ chí minh", "hcm", "tp hcm", "tp.hcm", "thành phố hồ chí minh",
    "sài gòn", "saigon", "sg", ""
}

MAX_NEW_TOKENS = 512
TEMPERATURE = 0.0
TOP_P = 0.9

def _get_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"

DEVICE = _get_device()

MULTI_INTENT_ENABLED = os.getenv("MULTI_INTENT_ENABLED", "False").lower() == "true"

# Feature flags for Context Slimming & Memory
ENABLE_LONG_TERM_MEMORY = os.getenv("ENABLE_LONG_TERM_MEMORY", "False").lower() == "true"
ENABLE_CONVERSATION_SUMMARY = os.getenv("ENABLE_CONVERSATION_SUMMARY", "False").lower() == "true"
SLIM_CONTEXT = os.getenv("SLIM_CONTEXT", "True").lower() == "true"
HISTORY_STORE_TURNS = int(os.getenv("HISTORY_STORE_TURNS", "10"))
HISTORY_PROMPT_TURNS = int(os.getenv("HISTORY_PROMPT_TURNS", "2"))

# Server Host & Port Settings - Default to 8003 for standalone project
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("STANDALONE_SERVER_PORT", "8003"))
