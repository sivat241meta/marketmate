from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

from app.meta.sam import find_boxes
from app.models import Box, Frame

#: Card photo ratio, long side cap and JPEG quality for item photos.
PHOTO_RATIO = (4, 3)
PHOTO_LONG_SIDE = 1200
PHOTO_QUALITY = 88
#: Smallest allowed short side of a photo crop, in pixels.
MIN_SHORT_SIDE = 360
#: Never enlarge a crop by more than this factor when saving.
MAX_UPSCALE = 1.5
#: Largest accepted seller photo upload (8 MB).
MAX_PHOTO_UPLOAD_BYTES = 8 * 1024 * 1024


class BadPhotoUpload(ValueError):
    """A retake upload that is too big or not an image."""


def sharpness_score(image: Path) -> float:
    """Variance of a FIND_EDGES filter on a small grey copy (higher=sharper)."""
    with Image.open(image) as img:
        grey = img.convert("L")
        grey.thumbnail((320, 320), Image.LANCZOS)
        edges = grey.filter(ImageFilter.FIND_EDGES)
        return ImageStat.Stat(edges).var[0]


def rank_by_sharpness(frames: list[Frame]) -> list[Frame]:
    """Frames sorted sharpest-first; unreadable files sink to the end."""
    scored = []
    for frame in frames:
        try:
            score = sharpness_score(frame.path)
        except OSError:
            score = -1.0
        scored.append((score, frame.t_ms, frame))
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [frame for _, _, frame in scored]


def _fit_photo_box(left: int, top: int, right: int, bottom: int,
                   width: int, height: int) -> tuple[int, int, int, int]:
    """4:3 box around a union's centre: contains it when it fits the frame,
    shrinks to the largest fitting 4:3 box when it does not, then grows to
    the short-side floor, always keeping the 4:3 ratio."""
    target = PHOTO_RATIO[0] / PHOTO_RATIO[1]
    box_w, box_h = max(right - left, 1), max(bottom - top, 1)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    if box_w / box_h < target:
        need_w, need_h = box_h * target, float(box_h)
    else:
        need_w, need_h = float(box_w), box_w / target
    fit = min(1.0, width / need_w, height / need_h)
    need_w, need_h = round(need_w * fit), round(need_h * fit)
    short = min(need_w, need_h)
    if 0 < short < MIN_SHORT_SIDE:
        grow = MIN_SHORT_SIDE / short
        refit = min(1.0, width / (need_w * grow), height / (need_h * grow))
        need_w = round(need_w * grow * refit)
        need_h = round(need_h * grow * refit)
    left = min(max(round(cx - need_w / 2), 0), max(width - need_w, 0))
    top = min(max(round(cy - need_h / 2), 0), max(height - need_h, 0))
    return left, top, left + need_w, top + need_h


def _centre_box(width: int, height: int, frac: float) -> tuple[int, int, int, int]:
    """Centre 4:3 box covering ``frac`` of the frame's width if it fits."""
    target = PHOTO_RATIO[0] / PHOTO_RATIO[1]
    box_w = round(width * frac)
    box_h = round(box_w / target)
    if box_h > height:
        box_h = round(height * frac)
        box_w = round(box_h * target)
    box_w, box_h = min(box_w, width), min(box_h, height)
    left = (width - box_w) // 2
    top = (height - box_h) // 2
    return left, top, left + box_w, top + box_h


def crop_box(boxes: list[Box], width: int, height: int) -> tuple[int, int, int, int]:
    """4:3 photo box: union of the 3 largest boxes + 6% pad, else 70% centre."""
    if not boxes:
        left, top, right, bottom = _centre_box(width, height, 0.7)
    else:
        biggest = sorted(boxes, key=lambda b: (b.x2 - b.x1) * (b.y2 - b.y1),
                         reverse=True)[:3]
        union = (min(b.x1 for b in biggest), min(b.y1 for b in biggest),
                 max(b.x2 for b in biggest), max(b.y2 for b in biggest))
        pad = 0.06 * min(union[2] - union[0], union[3] - union[1])
        left = max(0, round(union[0] - pad))
        top = max(0, round(union[1] - pad))
        right = min(width, round(union[2] + pad))
        bottom = min(height, round(union[3] + pad))
    return _fit_photo_box(left, top, right, bottom, width, height)


def clean_crop(crop: Image.Image) -> Image.Image:
    """Light clean-up: cap the long side, autocontrast, gentle sharpening."""
    long_side = max(crop.size)
    if long_side > PHOTO_LONG_SIDE:
        ratio = PHOTO_LONG_SIDE / long_side
        crop = crop.resize((max(1, round(crop.width * ratio)),
                            max(1, round(crop.height * ratio))),
                           Image.LANCZOS)
    crop = ImageOps.autocontrast(crop, cutoff=1)
    return crop.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70,
                                               threshold=3))


def save_photo(crop: Image.Image, out: Path) -> Path:
    """Save a cleaned crop as a progressive JPEG, never upscaled past 1.5x."""
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, "JPEG", quality=PHOTO_QUALITY, progressive=True,
              optimize=True)
    return out


def crop_to_boxes(image: Path, boxes: list[Box], out: Path) -> Path:
    """Cut a 4:3 product photo and save the cleaned JPEG."""
    with Image.open(image) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        crop = rgb.crop(crop_box(boxes, width, height))
    return save_photo(clean_crop(crop), out)


def centre_photo(image: Path, out: Path) -> Path:
    """Cut the 70% centre 4:3 photo (retakes and extra candidates)."""
    return crop_to_boxes(image, [], out)


def save_retake(data: bytes, out: Path) -> Path:
    """Save a seller-taken photo: verified image, no EXIF, cleaned 4:3 JPEG."""
    if len(data) > MAX_PHOTO_UPLOAD_BYTES:
        raise BadPhotoUpload("photo is bigger than 8 MB")
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
    except Exception as exc:
        raise BadPhotoUpload("not an image") from exc
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise BadPhotoUpload("not an image") from exc
    img = ImageOps.exif_transpose(img)
    crop = img.crop(crop_box([], img.width, img.height))
    return save_photo(clean_crop(crop), out)


def make_photo(frame: Frame, noun: str, out: Path, *, ledger, settings) -> Path:
    """Cut the product out of its best frame. Data URLs work, so no public_tmp."""
    boxes = find_boxes(frame.path, noun, ledger=ledger, settings=settings)
    return crop_to_boxes(frame.path, boxes, out)


def window_frames(frames: list[Frame], picked: Frame,
                  radius_ms: int = 1000) -> list[Frame]:
    """Frames within ±``radius_ms`` of the picked frame, sharpest first."""
    nearby = [f for f in frames if abs(f.t_ms - picked.t_ms) <= radius_ms]
    if picked not in nearby:
        nearby.append(picked)
    return rank_by_sharpness(nearby)


def make_candidates(frames: list[Frame], picked: Frame, noun: str,
                    out_stem: Path, *, ledger, settings,
                    count: int = 3) -> list[str]:
    """Up to ``count`` candidate photos, sharpest first.

    Only the sharpest frame uses SAM; the rest are centre crops, so the
    SAM cost never grows. Returns the saved file names.
    """
    ranked = window_frames(frames, picked)
    seen: set[str] = set()
    distinct = []
    for frame in ranked:
        key = str(frame.path)
        if key not in seen:
            seen.add(key)
            distinct.append(frame)
    saved = []
    for pos, frame in enumerate(distinct[:count]):
        out = out_stem.parent / f"{out_stem.name}_c{pos}.jpg"
        if pos == 0:
            boxes = find_boxes(frame.path, noun, ledger=ledger,
                               settings=settings)
            saved.append(str(crop_to_boxes(frame.path, boxes, out)))
        else:
            saved.append(str(centre_photo(frame.path, out)))
    return saved
