from pathlib import Path

from .extractors import extract_text

_SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _SUPPORTED_IMAGE_EXT


def ocr_image(path: Path) -> str:
    """Qwen-OCR wrapper (Phase 4 hardens this; Phase 1 stub raises)."""
    raise NotImplementedError(
        "Qwen-OCR not wired yet: install the model and set OCR_ENABLED=1. "
        "Scanned/photographed documents are not supported in Phase 1."
    )


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