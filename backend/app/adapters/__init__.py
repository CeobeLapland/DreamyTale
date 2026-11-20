from backend.app.adapters.base import (
    AdapterError,
    AdapterResponseError,
    AdapterUnavailableError,
)
from backend.app.adapters.ocr import OCRAdapter, OCRBlock, OCRResult

__all__ = [
    "AdapterError",
    "AdapterResponseError",
    "AdapterUnavailableError",
    "OCRAdapter",
    "OCRBlock",
    "OCRResult",
]