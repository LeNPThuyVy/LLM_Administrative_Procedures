import json
import hashlib
from pathlib import Path
from datetime import datetime


VERSION_FILE = Path("data/.ingestion_versions.json")


class VersionTracker:
    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        if VERSION_FILE.exists():
            return json.loads(
                VERSION_FILE.read_text(encoding="utf-8")
            )
        return {}

    def _save(self) -> None:
        VERSION_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        VERSION_FILE.write_text(
            json.dumps(
                self._data,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()

        with path.open("rb") as f:
            for chunk in iter(
                lambda: f.read(1024 * 1024),
                b"",
            ):
                h.update(chunk)

        return h.hexdigest()

    def _hash_path(self, path: Path) -> str:
        if path.is_file():
            return self._hash_file(path)

        if path.is_dir():
            h = hashlib.sha256()

            files = sorted(
                p
                for p in path.rglob("*")
                if p.is_file()
            )

            for file_path in files:
                relative = file_path.relative_to(path)

                h.update(
                    str(relative).encode("utf-8")
                )

                h.update(
                    self._hash_file(file_path).encode("utf-8")
                )

            return h.hexdigest()

        raise FileNotFoundError(
            f"Source path not found: {path}"
        )

    def _make_key(
        self,
        domain_id: str,
        path: Path,
    ) -> str:
        return f"{domain_id}:{path.resolve()}"

    def has_changed(
        self,
        domain_id: str,
        path: Path,
    ) -> bool:
        key = self._make_key(
            domain_id,
            path,
        )

        current_hash = self._hash_path(path)

        old_hash = (
            self._data
            .get(key, {})
            .get("hash")
        )

        return old_hash != current_hash

    def mark_indexed(
        self,
        domain_id: str,
        path: Path,
    ) -> None:
        key = self._make_key(
            domain_id,
            path,
        )

        self._data[key] = {
            "hash": self._hash_path(path),
            "indexed_at": datetime.now().isoformat(),
        }

        self._save()