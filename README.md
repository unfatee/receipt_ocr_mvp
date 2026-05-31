# OCR MVP for receipts and invoices

Минимально жизнеспособный продукт для темы: распознавание чеков и накладных с извлечением даты, суммы, магазина и списка товаров.

## Что есть в MVP

- веб-интерфейс для загрузки изображения;
- API-эндпоинт `POST /api/parse`;
- OCR через `rapidocr-onnxruntime`;
- извлечение полей регулярными выражениями и эвристиками;
- пример изображения чека;
- скрипт оценки качества парсера на текстовых примерах.

## Запуск

```powershell
cd receipt_ocr_mvp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --port 8000
```

После запуска откройте:

```text
http://127.0.0.1:8000
```

## API

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/parse" -F "file=@examples/sample_receipt.png"
```

Ответ возвращается в JSON:

```json
{
  "store_name": "FRESHMARKET",
  "date": "2026-05-30",
  "total_amount": 12.6,
  "items": [
    {"name": "MILK", "amount": 2.5},
    {"name": "BREAD", "amount": 1.2}
  ],
  "raw_text": "...",
  "confidence": 0.93
}
```

## Проверка парсера

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_parser.py
```

Скрипт сравнивает извлеченные поля с эталонными значениями из `examples/sample_receipts.jsonl`.

