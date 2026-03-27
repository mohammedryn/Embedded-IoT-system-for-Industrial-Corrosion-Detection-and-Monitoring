#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def _base_canvas() -> Image.Image:
    return Image.new("RGB", (1280, 720), color=(160, 165, 170))


def _save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", quality=95)


def build_clean(path: Path) -> None:
    img = _base_canvas()
    d = ImageDraw.Draw(img)
    d.rectangle((430, 120, 850, 620), fill=(175, 180, 186))
    _save(img, path)


def build_corroded(path: Path) -> None:
    img = _base_canvas()
    d = ImageDraw.Draw(img)
    d.rectangle((430, 120, 850, 620), fill=(110, 95, 80))
    for i in range(220):
        x = 450 + (i * 17) % 370
        y = 140 + (i * 29) % 450
        r = 4 + (i % 6)
        color = (155 + (i % 40), 70 + (i % 40), 20 + (i % 30))
        d.ellipse((x - r, y - r, x + r, y + r), fill=color)
    for i in range(60):
        x = 460 + (i * 31) % 350
        y = 150 + (i * 43) % 430
        d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(35, 30, 25))
    _save(img, path)


def build_blurred(path: Path) -> None:
    img = _base_canvas()
    d = ImageDraw.Draw(img)
    d.rectangle((430, 120, 850, 620), fill=(175, 180, 186))
    img = img.filter(ImageFilter.GaussianBlur(radius=7.0))
    _save(img, path)


def build_overexposed(path: Path) -> None:
    img = Image.new("RGB", (1280, 720), color=(255, 255, 255))
    _save(img, path)


def build_underexposed(path: Path) -> None:
    img = Image.new("RGB", (1280, 720), color=(4, 4, 4))
    _save(img, path)


def main() -> None:
    root = Path("data/sessions/c04/test_images")
    build_clean(root / "clean_1.jpg")
    build_clean(root / "clean_2.jpg")
    build_corroded(root / "corroded_1.jpg")
    build_corroded(root / "corroded_2.jpg")
    build_blurred(root / "blurred.jpg")
    build_overexposed(root / "overexposed.jpg")
    build_underexposed(root / "underexposed.jpg")
    print(f"Synthetic images generated in {root}")


if __name__ == "__main__":
    main()
