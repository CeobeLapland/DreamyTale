"""Free local OCR via RapidOCR (ONNX Runtime).

Supports both the legacy `rapidocr_onnxruntime` package and the newer `rapidocr`
package. The engine is loaded lazily so importing this module is cheap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .base import OCRItem


def _as_bbox(box: Any) -> tuple[int, int, int, int] | None:
    try:
        values = list(box)
    except TypeError:
        return None
    if not values:
        return None

    points: list[tuple[float, float]] = []
    if all(isinstance(v, (int, float)) for v in values):
        if len(values) == 4:
            x1, y1, x2, y2 = map(float, values)
            points = [(x1, y1), (x2, y2)]
        elif len(values) == 8:
            points = [(float(values[i]), float(values[i + 1])) for i in range(0, 8, 2)]
        else:
            return None
    else:
        for point in values:
            pair = list(point)
            if len(pair) < 2:
                continue
            points.append((float(pair[0]), float(pair[1])))

    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1, y1, x2, y2 = round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return x1, y1, x2, y2


class RapidOCRProvider:
    name = "rapidocr"

    def __init__(self, max_side: int = 1600, **kwargs: Any) -> None:
        self.max_side = max_side
        self.kwargs = kwargs
        self._engine: Any = None
        self._api: str | None = None
        self._error: str | None = None

    def _load(self) -> bool:
        if self._engine is not None:
            return True
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore

            self._engine = RapidOCR()
            self._api = "rapidocr_onnxruntime"
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = f"{exc}"

        try:
            from rapidocr import RapidOCR  # type: ignore

            self._engine = RapidOCR()
            self._api = "rapidocr"
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = f"{self._error}; {exc}"
            return False

    def available(self) -> bool:
        return self._load()

    def _iter_results(self, result: Any) -> Iterable[tuple[Any, str, float]]:
        if isinstance(result, tuple):
            result = result[0]

        boxes = getattr(result, "boxes", None)
        txts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is not None and txts is not None:
            for box, text, score in zip(boxes, txts, scores or [0.5] * len(txts)):
                yield box, str(text), float(score)
            return

        for line in result or []:
            try:
                box, text, score = line[0], line[1], line[2]
            except (TypeError, IndexError):
                continue
            yield box, str(text), float(score)

    def recognize(self, image_path: Path) -> list[OCRItem]:
        if not self._load():
            raise RuntimeError(f"RapidOCR unavailable: {self._error}")

        try:
            import numpy as np
            from PIL import Image
        except ImportError as exc:  # noqa: BLE001
            raise RuntimeError(f"RapidOCR image deps missing: {exc}") from exc

        with Image.open(image_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            scale = min(1.0, self.max_side / max(width, height)) if max(width, height) else 1.0
            if scale < 1.0:
                resized = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
            else:
                resized = image
            # RapidOCR's numpy path follows OpenCV's BGR convention.
            array = np.asarray(resized)[:, :, ::-1].copy()
            result = self._engine(array)

        inverse = 1.0 / scale if scale else 1.0
        items: list[OCRItem] = []
        for box, text, score in self._iter_results(result):
            text = text.strip()
            bbox = _as_bbox(box)
            if not text or bbox is None:
                continue
            x1, y1, x2, y2 = bbox
            scaled = (
                max(0, min(width, round(x1 * inverse))),
                max(0, min(height, round(y1 * inverse))),
                max(0, min(width, round(x2 * inverse))),
                max(0, min(height, round(y2 * inverse))),
            )
            if scaled[2] - scaled[0] < 2 or scaled[3] - scaled[1] < 2:
                continue
            items.append(OCRItem(text=text, bbox_px=scaled, confidence=max(0.0, min(1.0, score))))
        return items
