from pathlib import Path

from ..config import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(settings.asr_model, device="cpu", compute_type="int8")
    return _model


def transcribe(path: Path) -> str:
    segments, _ = _get_model().transcribe(str(path))
    return " ".join(s.text.strip() for s in segments).strip()