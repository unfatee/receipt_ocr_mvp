from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "examples" / "sample_receipts.jsonl"
sys.path.insert(0, str(ROOT))

from receipt_ocr.parser import parse_receipt_text


def main() -> None:
    total = 0
    correct = {"store_name": 0, "date": 0, "total_amount": 0}

    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sample = json.loads(line)
        expected = sample["expected"]
        parsed = parse_receipt_text(sample["text"])
        total += 1
        for field in correct:
            actual = getattr(parsed, field)
            if actual == expected[field]:
                correct[field] += 1

    print(f"Samples: {total}")
    for field, hits in correct.items():
        print(f"{field}: {hits / total:.2%}")


if __name__ == "__main__":
    main()
