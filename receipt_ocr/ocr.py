from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageOps
from pydantic import BaseModel, Field


class OCRLine(BaseModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: list[list[float]]


class OCRResult(BaseModel):
    text: str
    confidence: float | None
    lines: list[OCRLine]


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _prepare_image(image_bytes: bytes) -> bytes:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image = ImageOps.exif_transpose(image)
    max_side = 1800
    width, height = image.size
    scale = min(max_side / max(width, height), 1.0)
    if scale < 1.0:
        image = image.resize((int(width * scale), int(height * scale)))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def run_ocr(image_bytes: bytes) -> OCRResult:
    prepared = _prepare_image(image_bytes)
    result, _elapsed = _engine()(prepared)

    if not result:
        return OCRResult(text="", confidence=None, lines=[])

    lines: list[OCRLine] = []
    for row in result:
        bbox, text, confidence = row
        clean_text = " ".join(str(text).split())
        if clean_text:
            lines.append(
                OCRLine(
                    text=clean_text,
                    confidence=float(confidence),
                    bbox=[[float(x), float(y)] for x, y in bbox],
                )
            )

    lines.sort(key=lambda line: (min(point[1] for point in line.bbox), min(point[0] for point in line.bbox)))
    text = "\n".join(line.text for line in lines)
    avg_confidence = sum(line.confidence for line in lines) / len(lines) if lines else None
    return OCRResult(text=text, confidence=avg_confidence, lines=lines)

