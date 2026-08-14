import base64
from pathlib import Path

import ollama
import pymupdf

from ..config import settings
from .extractors import extract_text

_SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}
_RASTER_DPI = 200


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_IMAGE_EXT


def _ocr_bytes(image_bytes: bytes) -> str:
    image = base64.b64encode(image_bytes).decode()
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


def ocr_image(path: Path) -> str:
    if not settings.ocr_enabled:
        raise ValueError(
            "OCR is disabled (OCR_ENABLED=1 needed); scanned/photographed documents are not supported"
        )
    return _ocr_bytes(path.read_bytes())


def _rasterize_pdf(path: Path) -> list[bytes]:
    pages: list[bytes] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=_RASTER_DPI)
            pages.append(pix.tobytes("png"))
    return pages


def ocr_pdf(path: Path) -> str:
    if not settings.ocr_enabled:
        raise ValueError(
            "OCR is disabled (OCR_ENABLED=1 needed); scanned/photographed documents are not supported"
        )
    parts = [_ocr_bytes(png) for png in _rasterize_pdf(path)]
    return "\n\n".join(p for p in parts if p)


def extract_doc(path: Path) -> str:
    if is_image(path):
        return ocr_image(path)
    if path.suffix.lower() == ".pdf" and not _has_text_layer(path):
        return ocr_pdf(path)
    return extract_text(path)


def _has_text_layer(path: Path) -> bool:
    try:
        from .extractors import has_text_layer

        return has_text_layer(path)
    except Exception:
        return False