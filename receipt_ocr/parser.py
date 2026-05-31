from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field


TOTAL_KEYWORDS = (
    "total",
    "grand total",
    "amount due",
    "amount",
    "итого",
    "сумма",
    "к оплате",
    "оплата",
)

SKIP_ITEM_KEYWORDS = (
    "total",
    "subtotal",
    "tax",
    "vat",
    "cash",
    "card",
    "change",
    "итого",
    "налог",
    "ндс",
    "сдача",
    "карта",
    "наличные",
)


class ReceiptItem(BaseModel):
    name: str
    amount: float


class ParsedReceipt(BaseModel):
    store_name: str | None
    date: str | None
    total_amount: float | None
    items: list[ReceiptItem] = Field(default_factory=list)
    raw_text: str
    confidence: float
    warnings: list[str] = Field(default_factory=list)


def _amount_to_float(value: str) -> float | None:
    value = value.strip()
    value = re.sub(r"[^\d,.\-]", "", value)
    if not value:
        return None
    if "," in value and "." in value:
        value = value.replace(",", "")
    else:
        value = value.replace(",", ".")
    try:
        return round(float(value), 2)
    except ValueError:
        return None


def _normalize_date(parts: tuple[int, int, int]) -> str | None:
    year, month, day = parts
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_date(text: str) -> str | None:
    patterns = [
        r"(?P<y>20\d{2}|19\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})",
        r"(?P<d>\d{1,2})[-.](?P<m>\d{1,2})[-.](?P<y>20\d{2}|19\d{2}|\d{2})",
        r"(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>20\d{2}|19\d{2}|\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        y = int(match.group("y"))
        m = int(match.group("m"))
        d = int(match.group("d"))
        normalized = _normalize_date((y, m, d))
        if normalized:
            return normalized
    return None


def extract_total(lines: list[str]) -> float | None:
    candidates: list[float] = []
    for line in lines:
        normalized = line.lower()
        if any(keyword in normalized for keyword in TOTAL_KEYWORDS):
            amounts = re.findall(r"[-+]?\d+[,.]\d{2}|[-+]?\d{2,}", line)
            for amount in amounts:
                value = _amount_to_float(amount)
                if value is not None:
                    candidates.append(value)
    if candidates:
        return max(candidates)

    fallback = []
    for line in lines:
        for amount in re.findall(r"[-+]?\d+[,.]\d{2}", line):
            value = _amount_to_float(amount)
            if value is not None:
                fallback.append(value)
    return max(fallback) if fallback else None


def extract_store(lines: list[str]) -> str | None:
    for line in lines[:8]:
        clean = line.strip(" -:;")
        lower = clean.lower()
        if len(clean) < 3:
            continue
        if re.search(r"\d{2,}", clean):
            continue
        if any(keyword in lower for keyword in TOTAL_KEYWORDS):
            continue
        if any(word in lower for word in ("receipt", "invoice", "date", "касса", "чек")):
            continue
        return clean
    return None


def extract_items(lines: list[str]) -> list[ReceiptItem]:
    items: list[ReceiptItem] = []
    pattern = re.compile(r"^(?P<name>.+?)\s+(?P<amount>\d+[,.]\d{2})\s*$")
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in SKIP_ITEM_KEYWORDS):
            continue
        match = pattern.search(line)
        if not match:
            continue
        name = re.sub(r"\s{2,}", " ", match.group("name")).strip(" -:")
        amount = _amount_to_float(match.group("amount"))
        if name and amount is not None:
            items.append(ReceiptItem(name=name, amount=amount))
    return items


def parse_receipt_text(text: str, ocr_confidence: float | None = None) -> ParsedReceipt:
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    compact_text = "\n".join(lines)
    parsed_date = extract_date(compact_text)
    total = extract_total(lines)
    store = extract_store(lines)
    items = extract_items(lines)

    warnings = []
    if not compact_text:
        warnings.append("Не получен распознанный текст. Загрузите более четкое изображение или вставьте OCR-текст вручную.")
    if parsed_date is None:
        warnings.append("Дата не найдена.")
    if total is None:
        warnings.append("Итоговая сумма не найдена.")
    if store is None:
        warnings.append("Название магазина не найдено.")

    field_score = sum(value is not None for value in (parsed_date, total, store)) / 3
    ocr_score = ocr_confidence if ocr_confidence is not None else 0.75
    confidence = round((field_score * 0.55) + (ocr_score * 0.45), 3)

    return ParsedReceipt(
        store_name=store,
        date=parsed_date,
        total_amount=total,
        items=items,
        raw_text=compact_text,
        confidence=confidence,
        warnings=warnings,
    )
