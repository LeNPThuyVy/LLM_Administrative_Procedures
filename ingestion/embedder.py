import torch
from FlagEmbedding import BGEM3FlagModel


class BGEEmbedder:
    _instances = {}

    def __new__(cls, config):
        key = config.embedding_model
        if key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, config):
        if getattr(self, "_initialized", False):
            return

        self.config = config
        self._model = None
        self.use_cuda = torch.cuda.is_available()
        self.batch_size = 32 if self.use_cuda else 12
        self._initialized = True

    def _get_model(self):
        if self._model is None:
            print(f"[embedder] Loading model: {self.config.embedding_model}")
            print(f"[embedder] Device: {'CUDA' if self.use_cuda else 'CPU'}")
            print(f"[embedder] Batch size: {self.batch_size}")

            self._model = BGEM3FlagModel(
                self.config.embedding_model,
                use_fp16=self.use_cuda,
            )

        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model = self._get_model()

        output = model.encode(
            texts,
            batch_size=self.batch_size,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )

        return output["dense_vecs"].tolist()