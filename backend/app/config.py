from dataclasses import dataclass
import os

from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("NOTE_MASTER_DATA_DIR", "data"))
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    ollama_extract_model: str = os.getenv("OLLAMA_EXTRACT_MODEL", "llama3.2:3b")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "0") == "1"
    ocr_model: str = os.getenv("OCR_MODEL", "qwen2.5vl:3b")
    asr_model: str = os.getenv("ASR_MODEL", "base")
    memory_enabled: bool = os.getenv("MEMORY_ENABLED", "1") == "1"
    memory_url: str = os.getenv("MEMORY_URL", "http://127.0.0.1:6767")
    memory_api_key: str = os.getenv("MEMORY_API_KEY", "")
    memory_container_tag: str = os.getenv("MEMORY_CONTAINER_TAG", "user_main")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "note_master.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


settings = Settings()