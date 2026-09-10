
from pathlib import Path 

BASE_DIR = Path(__file__).resolve().parent

PROCEDURES_PATH = BASE_DIR / "data" / "procedures.json"
CHROMA_PATH = BASE_DIR / "data" / "chroma_db"

COLLECTION_NAME = "procedures"

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 200

DEFAULT_TOP_K = 5
