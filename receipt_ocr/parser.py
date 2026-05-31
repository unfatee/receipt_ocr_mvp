from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field


TOTAL_KEYWORDS = (
    "total",
    "totai",
    "grand total",
    "round total",
    "rounddtotal",
    "rounded total",
    "amount due",
    "итого",
    "сумма",
    "к оплате",
)

SKIP_ITEM_KEYWORDS = (
    "total",
    "totai",
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


def _money_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.findall(r"(?<!\d)\d{1,6}[,.]\d{2,3}(?!\d)", text):
        value = _amount_to_float(match)
        if value is not None:
            values.append(value)
    return values


def _looks_like_money_only(text: str) -> bool:
    clean = text.strip()
    return bool(re.fullmatch(r"[*\s]*\d{1,6}[,.]\d{2,3}[*\s]*", clean))


def _total_keyword_score(text: str) -> int:
    normalized = re.sub(r"[^a-zа-я0-9]+", "", text.lower())
    if any(word in normalized for word in ("rounddtotal", "roundedtotal", "grandtotal", "roundtotal", "итого", "коплате")):
        return 4
    if "total" in normalized or "totai" in normalized:
        return 3
    if "amountdue" in normalized:
        return 3
    return 0


def _normalize_date(parts: tuple[int, int, int]) -> str | None:
    year, month, day = parts
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_date(text: str) -> str | None:
    for match in re.finditer(r"(?P<y>20\d{2}|19\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})", text):
        normalized = _normalize_date((int(match.group("y")), int(match.group("m")), int(match.group("d"))))
        if normalized:
            return normalized

    for match in re.finditer(r"(?P<a>\d{1,2})[-./](?P<b>\d{1,2})[-./](?P<y>20\d{2}|19\d{2}|\d{2})", text):
        a = int(match.group("a"))
        b = int(match.group("b"))
        y = int(match.group("y"))
        if a > 12:
            candidates = [(y, b, a)]
        elif b > 12:
            candidates = [(y, a, b)]
        else:
            # SROIE receipts mostly use DD/MM/YYYY; keep MM/DD as fallback for ambiguous cases.
            candidates = [(y, b, a), (y, a, b)]
        for candidate in candidates:
            normalized = _normalize_date(candidate)
            if normalized:
                return normalized
    return None


def extract_total(lines: list[str]) -> float | None:
    candidates: list[tuple[int, int, float]] = []
    for index, line in enumerate(lines):
        score = _total_keyword_score(line)
        if not score:
            continue

        for amount in _money_values(line):
            if amount > 0:
                candidates.append((score, index, amount))

        for offset, nearby in enumerate(lines[index + 1 : index + 4], start=1):
            if _total_keyword_score(nearby) or any(word in nearby.lower() for word in ("cash", "change", "balance")):
                break
            if _looks_like_money_only(nearby):
                amount = _amount_to_float(nearby)
                if amount and amount > 0:
                    candidates.append((score + max(0, 3 - offset), index, amount))
                    break

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates[0][2]

    fallback = []
    for index, line in enumerate(lines):
        lower = line.lower()
        if any(word in lower for word in ("address", "jalan", "no.", "document", "invoice", "date")):
            continue
        if index < 6 and re.search(r"[a-zа-я]", lower):
            continue
        for value in _money_values(line):
            if value > 0:
                fallback.append(value)
    return max(fallback) if fallback else None


def extract_store(lines: list[str]) -> str | None:
    business_words = (
        "sdn",
        "bhd",
        "ltd",
        "llc",
        "enterprise",
        "market",
        "shop",
        "store",
        "hardware",
        "restaurant",
        "trading",
        "mart",
        "m)",
    )
    fallback: str | None = None
    for line in lines[:10]:
        clean = line.strip(" -:;")
        lower = clean.lower()
        if len(clean) < 3:
            continue
        if re.search(r"\d{2,}", clean):
            continue
        if _total_keyword_score(lower):
            continue
        if any(word in lower for word in ("receipt", "invoice", "date", "cash bill", "касса", "чек")):
            continue
        if any(word in lower for word in business_words):
            return clean
        if fallback is None:
            fallback = clean
    return fallback


def extract_items(lines: list[str]) -> list[ReceiptItem]:
    items: list[ReceiptItem] = []
    pattern = re.compile(r"^(?P<name>.+?)\s+(?P<amount>\d+[,.]\d{2})\s*$")
    item_zone = False
    for index, line in enumerate(lines):
        lower = line.lower()
        if any(marker in lower for marker in ("code/desc", "description", "cash bill", "item")):
            item_zone = True
            continue
        if _total_keyword_score(line):
            item_zone = False
        if any(keyword in lower for keyword in SKIP_ITEM_KEYWORDS):
            continue
        match = pattern.search(line)
        if match:
            name = re.sub(r"\s{2,}", " ", match.group("name")).strip(" -:")
            amount = _amount_to_float(match.group("amount"))
            if name and amount is not None:
                items.append(ReceiptItem(name=name, amount=amount))
            continue

        if not item_zone:
            continue
        if not re.search(r"[A-Za-zА-Яа-я]", line):
            continue
        if any(word in lower for word in ("price", "disc", "qty", "rm", "code", "desc", "cash", "member", "cashier")):
            continue
        if len(re.sub(r"[^A-Za-zА-Яа-я]+", "", line)) < 4:
            continue
        for nearby in lines[index + 1 : index + 6]:
            if _total_keyword_score(nearby):
                break
            if _looks_like_money_only(nearby):
                amount = _amount_to_float(nearby)
                if amount and amount > 0:
                    items.append(ReceiptItem(name=line, amount=amount))
                    break
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
