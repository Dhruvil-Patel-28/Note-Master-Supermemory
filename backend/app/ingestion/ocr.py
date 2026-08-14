import base64
from pathlib import Path

import ollama

from ..config import settings
from .extractors import extract_text

_SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_IMAGE_EXT


def ocr_image(path: Path) -> str:
    if not settings.ocr_enabled:
        raise ValueError(
            "OCR is disabled (OCR_ENABLED=1 needed); scanned/photographed documents are not supported"
        )
    image = base64.b64encode(path.read_bytes()).decode()
    response = ollama.Client(host=settings.ollama_host).chat(
        model=settings.ocr_model,
        messages=[
            {
                "role": "user",
                "content": "Transcribe all text exactly, preserving reading order and line breaks. Do not summarize.",
                "images": [image],
            }
        ],
        options={"temperature": 0.1},
    )
    return response["message"]["content"].strip()


def extract_doc(path: Path) -> str:
    if is_image(path) or not _has_text_layer(path):
        return ocr_image(path)
    return extract_text(path)


def _has_text_layer(path: Path) -> bool:
    try:
        from .extractors import has_text_layer

        return has_text_layer(path)
    except Exception:
        return False