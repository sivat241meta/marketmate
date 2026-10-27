from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.meta.sam import find_boxes
from app.models import Box, Frame


def crop_to_boxes(image: Path, boxes: list[Box], out: Path) -> Path:
    """Crop the padded union of the 6 largest boxes; centre 80% if none."""
    img = Image.open(image).convert("RGB")
    width, height = img.size
    if not boxes:
        left, top = int(width * 0.1), int(height * 0.1)
        right, bottom = width - left, height - top
    else:
        biggest = sorted(boxes, key=lambda b: (b.x2 - b.x1) * (b.y2 - b.y1),
                         reverse=True)[:6]
        union = (min(b.x1 for b in biggest), min(b.y1 for b in biggest),
                 max(b.x2 for b in biggest), max(b.y2 for b in biggest))
        pad = 0.08 * min(union[2] - union[0], union[3] - union[1])
        left = max(0, round(union[0] - pad))
        top = max(0, round(union[1] - pad))
        right = min(width, round(union[2] + pad))
        bottom = min(height, round(union[3] + pad))
    crop = img.crop((left, top, right, bottom))
    crop.thumbnail((800, 800), Image.LANCZOS)
    crop.save(out, "JPEG")
    return out


def make_photo(frame: Frame, noun: str, out: Path, *, ledger, settings) -> Path:
    """Cut the product out of its best frame. Data URLs work, so no public_tmp."""
    boxes = find_boxes(frame.path, noun, ledger=ledger, settings=settings)
    return crop_to_boxes(frame.path, boxes, out)
