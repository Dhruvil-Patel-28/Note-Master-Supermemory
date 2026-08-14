from dataclasses import dataclass
import os

from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("NOTE_MASTER_DATA_DIR", "data"))
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "0") == "1"
    ocr_model: str = os.getenv("OCR_MODEL", "qwen-ocr:small")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "note_master.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


settings = Settings()