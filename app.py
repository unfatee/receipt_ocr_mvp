from __future__ import annotations

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from receipt_ocr.ocr import run_ocr
from receipt_ocr.parser import parse_receipt_text


app = FastAPI(title="Receipt OCR MVP", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/parse")
async def parse_document(
    file: UploadFile | None = File(default=None),
    ocr_text: str | None = Form(default=None),
) -> JSONResponse:
    raw_text = (ocr_text or "").strip()
    ocr_confidence = None
    lines = []

    if file is not None and file.filename:
        image_bytes = await file.read()
        ocr_result = run_ocr(image_bytes)
        raw_text = ocr_result.text if not raw_text else raw_text
        ocr_confidence = ocr_result.confidence
        lines = ocr_result.lines

    parsed = parse_receipt_text(raw_text, ocr_confidence=ocr_confidence)
    payload = parsed.model_dump()
    payload["ocr_lines"] = [line.model_dump() for line in lines]
    return JSONResponse(payload)
