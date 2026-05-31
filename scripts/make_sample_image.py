from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "sample_receipt.png"


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\calibri.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def main() -> None:
    image = Image.new("RGB", (640, 900), "white")
    draw = ImageDraw.Draw(image)
    title_font = font(30)
    body_font = font(24)
    y = 50
    rows = [
        ("FRESH MARKET", title_font),
        ("123 MAIN STREET", body_font),
        ("DATE: 2026-05-30", body_font),
        ("", body_font),
        ("MILK 2.50", body_font),
        ("BREAD 1.20", body_font),
        ("COFFEE 8.90", body_font),
        ("", body_font),
        ("TOTAL 12.60", title_font),
    ]
    for text, current_font in rows:
        if text:
            draw.text((60, y), text, fill="black", font=current_font)
        y += 48
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()

