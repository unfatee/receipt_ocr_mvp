from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field


TOTAL_KEYWORDS = (
    "grand total", "grandtotal", "round total", "rounddtotal", "rounded total",
    "total amt", "total amount", "amount due", "balance due", "total incl", "total incl. of gst",
    "total excl", "net total", "nett total", "invoice total",
    "total", "totai", "ttl", "итого", "сумма", "к оплате",
)

STRONG_TOTAL_WORDS = (
    "grandtotal", "roundtotal", "rounddtotal", "roundedtotal", "totalamt", "totalamount",
    "amountdue", "balancedue", "invoicetotal", "totalincl", "коплате", "итого",
)

PAYMENT_WORDS = (
    "payment", "paid", "cash", "card", "visa", "master", "change", "balance", "tender",
    "refund", "deposit", "наличные", "карта", "сдача",
)

ADDRESS_OR_SERVICE_WORDS = (
    "address", "jalan", "jln", "street", "st.", "road", "rd.", "taman", "bandar",
    "selangor", "kuala", "lumpur", "invoice", "receipt", "cashier", "counter",
    "date", "time", "tel", "phone", "fax", "reg", "gst", "tax invoice", "company reg",
    "no.", "no:", "doc", "document", "member", "welcome",
)

SKIP_ITEM_KEYWORDS = (
    "total", "totai", "subtotal", "sub total", "tax", "vat", "gst", "sst", "cash",
    "card", "change", "payment", "paid", "balance", "round", "rounding", "discount",
    "disc", "invoice", "receipt", "cashier", "date", "time", "tel", "reg", "summary",
    "amount", "thank", "return", "итого", "налог", "ндс", "сдача", "карта", "наличные",
)

ITEM_HEADER_WORDS = (
    "description", "desc", "item", "product", "goods", "code/desc", "qty", "quantity",
    "price", "unit", "rm", "amount", "код", "товар", "наименование", "кол", "цена",
)

STORE_STOP_WORDS = (
    "tax invoice", "invoice", "receipt", "cash bill", "bill", "date", "cashier", "tel",
    "phone", "fax", "gst", "reg", "company reg", "sales", "welcome", "no.", "jalan", "jln",
    "street", "road", "taman", "bandar", "selangor", "квитанция", "чек",
)

BUSINESS_WORDS = (
    "sdn", "bhd", "ltd", "llc", "inc", "corp", "co.", "company", "enterprise", "trading",
    "market", "mart", "shop", "store", "hardware", "electrical", "restaurant", "cafe", "bakery",
    "pharmacy", "supermarket", "book", "food", "m)", "retail", "mini market",
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


def _normalize_line(line: str) -> str:
    line = line.replace("\u00a0", " ")
    line = line.replace("|", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _compact(text: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", text.lower())


def _amount_to_float(value: str) -> float | None:
    value = value.strip()
    value = re.sub(r"[^\d,.\-]", "", value)
    if not value or value in {".", ",", "-"}:
        return None

    # 1,234.56 -> 1234.56; 1.234,56 -> 1234.56
    if "," in value and "." in value:
        if value.rfind(".") > value.rfind(","):
            value = value.replace(",", "")
        else:
            value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", ".")

    try:
        return round(float(value), 2)
    except ValueError:
        return None


def _money_values(text: str) -> list[float]:
    values: list[float] = []
    patterns = [
        r"(?<!\d)(?:RM|MYR|USD|EUR|€|\$)?\s*\d{1,3}(?:[,.]\d{3})+[,.]\d{2}(?!\d)",
        r"(?<!\d)(?:RM|MYR|USD|EUR|€|\$)?\s*\d{1,6}[,.]\d{2,3}(?!\d)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = _amount_to_float(match)
            if value is not None and value >= 0:
                values.append(value)
    return values


def _looks_like_money_only(text: str) -> bool:
    clean = text.strip()
    return bool(re.fullmatch(r"[*\s]*(?:RM|MYR|USD|EUR|€|\$)?\s*\d{1,6}[,.]\d{2,3}[*\s]*", clean, re.I))


def _total_keyword_score(text: str) -> int:
    normalized = _compact(text)
    if any(word in normalized for word in STRONG_TOTAL_WORDS):
        return 6
    if "grand" in normalized and "total" in normalized:
        return 6
    if "round" in normalized and "total" in normalized:
        return 6
    if "total" in normalized or "totai" in normalized or "ttl" == normalized:
        return 4
    if any(word in normalized for word in ("сумма", "коплате")):
        return 4
    return 0


def _is_bad_total_context(text: str) -> bool:
    lower = text.lower()
    compact = _compact(text)
    if any(word in lower for word in PAYMENT_WORDS):
        return True
    # Tax/GST summary often has amounts that are not the final receipt total.
    if any(word in lower for word in ("gst summary", "tax summary", "tax (", "gst @", "sr @", "vat @")):
        return True
    if any(word in lower for word in ("subtotal", "sub total")):
        return True
    if any(word in compact for word in ("totalitem", "totalitems", "itemtotal")):
        return True
    return False


def _normalize_date(parts: tuple[int, int, int]) -> str | None:
    year, month, day = parts
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_date(text: str) -> str | None:
    # YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
    for match in re.finditer(r"(?P<y>20\d{2}|19\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})", text):
        normalized = _normalize_date((int(match.group("y")), int(match.group("m")), int(match.group("d"))))
        if normalized:
            return normalized

    # DD/MM/YYYY HH:MM, DD-MM-YY, MM/DD/YYYY. For ambiguous cases prefer DD/MM,
    # because SROIE/Malaysian receipts usually use day first.
    for match in re.finditer(r"(?P<a>\d{1,2})[-./](?P<b>\d{1,2})[-./](?P<y>20\d{2}|19\d{2}|\d{2})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", text):
        a = int(match.group("a"))
        b = int(match.group("b"))
        y = int(match.group("y"))
        if a > 12:
            candidates = [(y, b, a)]
        elif b > 12:
            candidates = [(y, a, b)]
        else:
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
        if not score or _is_bad_total_context(line):
            continue

        amounts = _money_values(line)
        if amounts:
            # Usually the last amount on the total line is the final value.
            for amount in amounts[-2:]:
                if amount > 0:
                    candidates.append((score * 10 + 3, index, amount))

        # Some receipts have label line followed by amount line.
        for offset, nearby in enumerate(lines[index + 1 : index + 5], start=1):
            if _is_bad_total_context(nearby):
                break
            nearby_score = _total_keyword_score(nearby)
            nearby_amounts = _money_values(nearby)
            if nearby_score and not nearby_amounts:
                continue
            if nearby_score and nearby_amounts:
                # New total-like line; it will be processed separately.
                break
            if _looks_like_money_only(nearby) or nearby_amounts:
                amount = (nearby_amounts[-1] if nearby_amounts else _amount_to_float(nearby))
                if amount and amount > 0:
                    candidates.append((score * 10 + max(0, 4 - offset), index, amount))
                    break

    if candidates:
        # Prefer stronger keyword and lower/late total lines. Do not simply choose max amount,
        # because payment/cash can be larger than total.
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    # Fallback: use lower-half money values, excluding addresses, dates, payment and header blocks.
    fallback: list[float] = []
    start = max(0, len(lines) // 3)
    for index, line in enumerate(lines[start:], start=start):
        lower = line.lower()
        if any(word in lower for word in ADDRESS_OR_SERVICE_WORDS + PAYMENT_WORDS):
            continue
        if any(word in lower for word in ("subtotal", "tax", "gst", "vat", "change", "payment")):
            continue
        for value in _money_values(line):
            if value > 0:
                fallback.append(value)
    return max(fallback) if fallback else None


def _store_line_score(line: str, index: int) -> int:
    clean = line.strip(" -:;.,")
    lower = clean.lower()
    if len(clean) < 3:
        return -100
    if any(word in lower for word in STORE_STOP_WORDS):
        return -80
    # Strong numbers in the header usually mean address/reg number, not store name.
    if re.search(r"\d{3,}", clean):
        return -50
    letters = len(re.findall(r"[A-Za-zА-Яа-я]", clean))
    if letters < 3:
        return -50
    score = 20 - index
    if any(word in lower for word in BUSINESS_WORDS):
        score += 25
    if clean.isupper():
        score += 8
    if re.search(r"[&()]", clean):
        score += 4
    return score


def extract_store(lines: list[str]) -> str | None:
    header = lines[:12]
    best_index: int | None = None
    best_score = -100

    for index, line in enumerate(header):
        score = _store_line_score(line, index)
        if score > best_score:
            best_score = score
            best_index = index

    if best_index is None or best_score < 0:
        return None

    parts = [header[best_index].strip(" -:;.,")]

    # Join nearby continuation lines, because many receipts split names:
    # HOME MASTER HARDWARE & / ELECTRICAL, ABC TRADING / SDN BHD, etc.
    for next_line in header[best_index + 1 : min(best_index + 4, len(header))]:
        clean = next_line.strip(" -:;.,")
        lower = clean.lower()
        if not clean:
            break
        if any(word in lower for word in STORE_STOP_WORDS):
            break
        if re.search(r"\d{3,}", clean):
            break
        letters = len(re.findall(r"[A-Za-zА-Яа-я]", clean))
        if letters < 3:
            break
        continuation = (
            parts[-1].endswith(("&", "(", "-"))
            or clean.isupper()
            or any(word in lower for word in BUSINESS_WORDS)
            or len(clean.split()) <= 3
        )
        if continuation:
            parts.append(clean)
        else:
            break

    store = " ".join(parts)
    store = re.sub(r"\s+", " ", store).strip()
    return store or None


def _is_probable_item_name(line: str) -> bool:
    lower = line.lower()
    if any(keyword in lower for keyword in SKIP_ITEM_KEYWORDS):
        return False
    if any(word in lower for word in ADDRESS_OR_SERVICE_WORDS):
        return False
    letters = len(re.findall(r"[A-Za-zА-Яа-я]", line))
    if letters < 3:
        return False
    if _total_keyword_score(line):
        return False
    # Avoid pure header rows like RM Code.
    if len(line.split()) <= 3 and all(word.lower().strip(":") in ITEM_HEADER_WORDS for word in line.split()):
        return False
    return True


def _clean_item_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip(" -:;.,")
    # Remove leading item numbers or bullets.
    name = re.sub(r"^\d{1,4}[).\-\s]+", "", name).strip()
    return name


def _dedupe_items(items: list[ReceiptItem]) -> list[ReceiptItem]:
    result: list[ReceiptItem] = []
    seen: set[tuple[str, float]] = set()
    for item in items:
        key = (re.sub(r"\W+", "", item.name.lower()), item.amount)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def extract_items(lines: list[str]) -> list[ReceiptItem]:
    items: list[ReceiptItem] = []
    item_zone = False
    pending_name: str | None = None

    # If a receipt does not have a clear item header, start looking after date/cashier/invoice area.
    soft_start = 0
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(word in lower for word in ("cashier", "date", "invoice", "receipt no", "bill no")):
            soft_start = i + 1

    for index, line in enumerate(lines):
        lower = line.lower()

        if any(marker in lower for marker in ITEM_HEADER_WORDS):
            item_zone = True
            pending_name = None
            # Header can include item words and no real product, so skip it.
            if not _money_values(line):
                continue

        if _total_keyword_score(line) or any(word in lower for word in ("subtotal", "sub total")):
            # Product list normally ends at subtotal/total block.
            if index > soft_start:
                item_zone = False
                pending_name = None
            continue

        if any(keyword in lower for keyword in SKIP_ITEM_KEYWORDS):
            continue

        amounts = _money_values(line)
        probable_name = _is_probable_item_name(line)

        # Case 1: previous line is name, current line is price/qty line:
        # 24MMX7Y M.ONE TAPE / 1.00 x 15.90 15.90 SR
        if amounts and pending_name:
            items.append(ReceiptItem(name=pending_name, amount=amounts[-1]))
            pending_name = None
            continue

        # Case 2: one-line item: NAME .... 12.30
        if amounts and probable_name:
            name_part = line
            for raw_amount in re.findall(r"(?:RM|MYR|USD|EUR|€|\$)?\s*\d{1,6}[,.]\d{2,3}", line, flags=re.I):
                name_part = name_part.replace(raw_amount, " ")
            name_part = re.sub(r"\b\d+(?:[,.]\d+)?\s*[xX*]\s*\d+(?:[,.]\d+)?\b", " ", name_part)
            name_part = re.sub(r"\b\d+(?:[,.]\d+)?\b", " ", name_part)
            name = _clean_item_name(name_part)
            if len(re.findall(r"[A-Za-zА-Яа-я]", name)) >= 3 and name.lower() not in {"x", "sr", "x sr", "rm code"}:
                items.append(ReceiptItem(name=name, amount=amounts[-1]))
                pending_name = None
                continue

        # Case 3: current line is probable name; store as pending if we are in/near item zone.
        if probable_name and (item_zone or index >= soft_start):
            # Do not let very top store/header lines become items.
            if index < max(4, soft_start) and not item_zone:
                continue
            pending_name = _clean_item_name(line)
            continue

        # Case 4: pure money line after pending item.
        if pending_name and (_looks_like_money_only(line) or amounts):
            amount = amounts[-1] if amounts else _amount_to_float(line)
            if amount and amount > 0:
                items.append(ReceiptItem(name=pending_name, amount=amount))
                pending_name = None

    return _dedupe_items(items)


def parse_receipt_text(text: str, ocr_confidence: float | None = None) -> ParsedReceipt:
    lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
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
    if not items:
        warnings.append("Товары не найдены. Возможно, OCR разбил таблицу на отдельные строки или чек имеет нестандартный формат.")

    field_score = sum(value is not None for value in (parsed_date, total, store)) / 3
    ocr_score = ocr_confidence if ocr_confidence is not None else 0.75
    item_bonus = 0.05 if items else 0.0
    confidence = min(1.0, round((field_score * 0.55) + (ocr_score * 0.40) + item_bonus, 3))

    return ParsedReceipt(
        store_name=store,
        date=parsed_date,
        total_amount=total,
        items=items,
        raw_text=compact_text,
        confidence=confidence,
        warnings=warnings,
    )
