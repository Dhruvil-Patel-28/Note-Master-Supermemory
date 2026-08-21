import base64
import logging
from pathlib import Path

import ollama
import pymupdf

from ..config import settings
from .extractors import extract_text

logger = logging.getLogger(__name__)

_SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}
_RASTER_DPI = 200

_converter = None


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_IMAGE_EXT


def _get_converter():
    """Lazy Docling singleton (asr.py pattern): the import alone costs ~30s
    and the layout models load on first convert, so this must never run at
    module import time — only inside the background ingest task."""
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
    return _converter


def docling_extract(path: Path) -> str:
    """Any PDF → markdown via Docling. Layout models give real tables for
    digital PDFs; its internal OCR (RapidOCR) covers image-only pages, so one
    path handles both born-digital and scanned documents."""
    result = _get_converter().convert(str(path))
    return result.document.export_to_markdown()


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


def _legacy_extract_pdf(path: Path) -> str:
    """Pre-Docling routing: text-layer PDFs via pypdf, image-only PDFs via
    per-page VLM OCR. Kept as the automatic fallback when Docling fails or
    DOCLING_ENABLED=0."""
    if not _has_text_layer(path):
        return ocr_pdf(path)
    return extract_text(path)


def extract_doc(path: Path) -> str:
    if is_image(path):
        return ocr_image(path)
    if path.suffix.lower() == ".pdf":
        if settings.docling_enabled:
            try:
                return docling_extract(path)
            except Exception as exc:
                logger.warning("docling conversion failed for %s (%s) — legacy extractor", path.name, exc)
        return _legacy_extract_pdf(path)
    return extract_text(path)


def _has_text_layer(path: Path) -> bool:
    try:
        from .extractors import has_text_layer

        return has_text_layer(path)
    except Exception:
        return False
