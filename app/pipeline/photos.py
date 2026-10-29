from __future__ import annotations

import io
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

from app.meta.sam import SamError, SamInstance, find_boxes, find_instances
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
#: SAM confidence floor for product instances and face hits.
PRODUCT_CONFIDENCE = 0.35
FACE_CONFIDENCE = 0.5
#: Noun for the face gate; a face covering this frame fraction blocks a frame.
FACE_NOUN = "face"
FACE_FRAME_FRACTION = 0.02
#: Cut-out cluster cap and candidate frames tried per item (bounds SAM cost:
#: at most 3 product calls and 3 face calls per item; typically 1 + 1).
#: Three, not two: on the owner's video the apples only showed on the
#: third-sharpest frame of the window.
MAX_CLUSTER = 4
MAX_TRIED_FRAMES = 3
#: Cut-out tile: square canvas, product fit, centre pushed slightly low.
CUTOUT_SIZE = 900
CUTOUT_FIT = 0.78
CUTOUT_LOW_OFFSET = 20
#: Candidate file suffixes: cut-out first (default), Task 59 crop second.
CUTOUT_SUFFIX = "_cut"
ORIGINAL_SUFFIX = "_orig"


class BadPhotoUpload(ValueError):
    """A retake upload that is too big or not an image."""


class NoCutout(ValueError):
    """No usable mask, so no cut-out tile can be built."""


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


def _passes(confidence: float | None, floor: float) -> bool:
    """A missing confidence never filters (older SAM replies omit ``c``)."""
    return confidence is None or confidence >= floor


def _box_area(box: Box) -> int:
    return max(box.x2 - box.x1 + 1, 1) * max(box.y2 - box.y1 + 1, 1)


def _touches(main: Box, other: Box, gap: int = 2) -> bool:
    """True when ``other`` overlaps the main box or touches its edge."""
    return not (other.x2 < main.x1 - gap or other.x1 > main.x2 + gap
                or other.y2 < main.y1 - gap or other.y1 > main.y2 + gap)


def _intersects(box: Box, area: tuple[int, int, int, int]) -> bool:
    """True when the box overlaps a (left, top, right, bottom) area."""
    left, top, right, bottom = area
    return not (box.x2 < left or box.x1 > right
                or box.y2 < top or box.y1 > bottom)


def main_cluster(instances: list[SamInstance]) -> list[SamInstance]:
    """Largest instance plus instances touching it, up to ``MAX_CLUSTER``."""
    if not instances:
        return []
    ranked = sorted(instances, key=lambda item: _box_area(item.box),
                    reverse=True)
    main = ranked[0]
    cluster = [main]
    for inst in ranked[1:]:
        if len(cluster) >= MAX_CLUSTER:
            break
        if _touches(main.box, inst.box):
            cluster.append(inst)
    return cluster


def cluster_box(cluster: list[SamInstance]) -> tuple[int, int, int, int]:
    """Union of the cluster's boxes as (left, top, right, bottom)."""
    return (min(i.box.x1 for i in cluster), min(i.box.y1 for i in cluster),
            max(i.box.x2 for i in cluster), max(i.box.y2 for i in cluster))


def face_blocks_frame(faces: list[Box], *,
                      frame_size: tuple[int, int],
                      crop_area: tuple[int, int, int, int],
                      cluster: tuple[int, int, int, int]) -> bool:
    """True when a confident face ruins the frame: it overlaps the 4:3 crop
    or the cut-out cluster's box, or covers ≥2% of the frame (a selfie)."""
    width, height = frame_size
    for face in faces:
        if face.confidence is not None and face.confidence < FACE_CONFIDENCE:
            continue
        if _box_area(face) >= FACE_FRAME_FRACTION * width * height:
            return True
        if _intersects(face, crop_area) or _intersects(face, cluster):
            return True
    return False


def _paste_clipped(canvas: Image.Image, tile: Image.Image,
                   left: int, top: int) -> None:
    """Paste a tile, clipping silently when it overhangs the canvas."""
    right, bottom = left + tile.width, top + tile.height
    keep = (max(-left, 0), max(-top, 0),
            tile.width - max(right - canvas.width, 0),
            tile.height - max(bottom - canvas.height, 0))
    if keep[2] <= keep[0] or keep[3] <= keep[1]:
        return
    canvas.paste(tile.crop(keep), (max(left, 0), max(top, 0)))


def place_masks(frame_size: tuple[int, int],
                cluster: list[SamInstance]) -> Image.Image:
    """Union of the cluster's decoded masks at their box positions.

    Each mask is box-local; when its raster differs from the box size (a
    pixel or two off), it is scaled to the box. Raises ``NoCutout`` when
    no mask decodes.
    """
    matte = Image.new("L", frame_size, 0)
    placed = 0
    for inst in cluster:
        if inst.mask is None:
            continue
        try:
            raster = inst.mask.raster()
        except SamError:
            continue
        mask = Image.frombytes(
            "L", (inst.mask.width, inst.mask.height),
            bytes(255 if bit else 0 for bit in raster))
        want = (max(inst.box.x2 - inst.box.x1 + 1, 1),
                max(inst.box.y2 - inst.box.y1 + 1, 1))
        if mask.size != want:
            mask = mask.resize(want, Image.NEAREST)
        layer = Image.new("L", frame_size, 0)
        _paste_clipped(layer, mask, inst.box.x1, inst.box.y1)
        matte = Image.frombytes(
            "L", matte.size,
            bytes(a | b for a, b in zip(matte.tobytes(), layer.tobytes())))
        placed += 1
    if not placed:
        raise NoCutout("no usable mask in cluster")
    return matte


def cutout_from_instances(image: Path, cluster: list[SamInstance],
                          out: Path) -> Path:
    """Quick-commerce tile: masked product on a 900×900 white canvas.

    The product fits 78% of the canvas, sits slightly low, and gets a
    soft contact shadow (blurred alpha, 6% opacity). Raises ``NoCutout``
    when no mask decodes.
    """
    with Image.open(image) as img:
        rgb = img.convert("RGB")
    matte = place_masks(rgb.size, cluster).filter(
        ImageFilter.GaussianBlur(1.5))
    bounds = matte.getbbox()
    if bounds is None:  # pragma: no cover - place_masks guarantees pixels
        raise NoCutout("empty matte")
    tight = rgb.crop(bounds)
    alpha = matte.crop(bounds)
    scale = CUTOUT_SIZE * CUTOUT_FIT / max(tight.size)
    size = (max(1, round(tight.width * scale)),
            max(1, round(tight.height * scale)))
    tight = tight.resize(size, Image.LANCZOS)
    alpha = alpha.resize(size, Image.LANCZOS)
    left = (CUTOUT_SIZE - size[0]) // 2
    top = (CUTOUT_SIZE - size[1]) // 2 + CUTOUT_LOW_OFFSET
    shadow = Image.new("L", (CUTOUT_SIZE, CUTOUT_SIZE), 0)
    _paste_clipped(shadow, alpha.filter(ImageFilter.GaussianBlur(14)),
                   left, top + 10)
    shadow = shadow.point(lambda value: round(value * 0.06))
    canvas = Image.composite(Image.new("RGB", canvas_size(), (0, 0, 0)),
                             Image.new("RGB", canvas_size(), (255, 255, 255)),
                             shadow)
    canvas.paste(tight, (left, top), alpha)
    return save_photo(canvas, out)


def canvas_size() -> tuple[int, int]:
    """Cut-out canvas size (square)."""
    return (CUTOUT_SIZE, CUTOUT_SIZE)


def is_cutout_photo(photo: str | Path | None) -> bool:
    """True when the photo file is a cut-out tile (by file suffix)."""
    return bool(photo) and Path(photo).stem.endswith(CUTOUT_SUFFIX)


def photo_kind(photo: str | Path | None) -> str | None:
    """``"cutout"``/``"original"`` for auto candidates, else None."""
    if not photo:
        return None
    stem = Path(photo).stem
    if stem.endswith(CUTOUT_SUFFIX):
        return "cutout"
    if stem.endswith(ORIGINAL_SUFFIX):
        return "original"
    return None


def blur_faces(img: Image.Image, faces: list[Box]) -> Image.Image:
    """Blur each confident face region (strong Gaussian) in place."""
    for face in faces:
        if face.confidence is not None and face.confidence < FACE_CONFIDENCE:
            continue
        pad_x = round((face.x2 - face.x1 + 1) * 0.2)
        pad_y = round((face.y2 - face.y1 + 1) * 0.2)
        left = max(face.x1 - pad_x, 0)
        top = max(face.y1 - pad_y, 0)
        right = min(face.x2 + pad_x + 1, img.width)
        bottom = min(face.y2 + pad_y + 1, img.height)
        if right <= left or bottom <= top:
            continue
        region = img.crop((left, top, right, bottom))
        radius = max(25, min(region.size) // 3)
        img.paste(region.filter(ImageFilter.GaussianBlur(radius)),
                  (left, top))
    return img


def _face_boxes_for(data: bytes, directory: Path, *, ledger,
                    settings) -> list[Box]:
    """SAM face boxes for raw upload bytes (via a temp file, always cleaned)."""
    handle, tmp = tempfile.mkstemp(suffix=".jpg", dir=str(directory))
    try:
        with open(handle, "wb") as stream:
            stream.write(data)
        return find_boxes(Path(tmp), FACE_NOUN, ledger=ledger,
                          settings=settings)
    finally:
        Path(tmp).unlink(missing_ok=True)


def save_retake(data: bytes, out: Path, *, ledger, settings) -> Path:
    """Save a seller-taken photo: verified, face-blurred, no EXIF, 4:3 JPEG.

    Bad uploads raise ``BadPhotoUpload`` before any SAM call; faces found
    by SAM stay in the photo but blurred.
    """
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
    out.parent.mkdir(parents=True, exist_ok=True)
    faces = _face_boxes_for(data, out.parent, ledger=ledger, settings=settings)
    blur_faces(img, faces)
    crop = img.crop(crop_box([], img.width, img.height))
    return save_photo(clean_crop(crop), out)


def _frame_size(image: Path) -> tuple[int, int]:
    with Image.open(image) as img:
        return img.size


def _choose_frame(frames: list[Frame], noun: str, *,
                  ledger, settings) -> tuple[Frame, list[SamInstance]] | None:
    """First tried frame with product instances and no blocking face.

    Tries at most ``MAX_TRIED_FRAMES`` frames, sharpest first. Returns
    None when no frame qualifies (no product anywhere, or every tried
    frame face-blocked).
    """
    for frame in frames[:MAX_TRIED_FRAMES]:
        instances = [inst for inst in find_instances(
            frame.path, noun, ledger=ledger, settings=settings)
            if _passes(inst.box.confidence, PRODUCT_CONFIDENCE)]
        if not instances:
            continue
        cluster = main_cluster(instances)
        size = _frame_size(frame.path)
        boxes = [inst.box for inst in cluster]
        faces = find_boxes(frame.path, FACE_NOUN, ledger=ledger,
                           settings=settings)
        if face_blocks_frame(faces, frame_size=size,
                             crop_area=crop_box(boxes, *size),
                             cluster=cluster_box(cluster)):
            continue
        return frame, cluster
    return None


def make_photo(frame: Frame, noun: str, out: Path, *, ledger,
               settings) -> Path | None:
    """Cut the product out of one frame: cut-out tile, else the 4:3 crop.

    Returns None (no photo) when SAM finds no instance of the noun or a
    face blocks the frame. No centre-crop fallback for automatic photos.
    """
    chosen = _choose_frame([frame], noun, ledger=ledger, settings=settings)
    if chosen is None:
        return None
    _, cluster = chosen
    try:
        return cutout_from_instances(frame.path, cluster, out)
    except NoCutout:
        return crop_to_boxes(frame.path, [inst.box for inst in cluster], out)


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
    """Cut-out (default) plus the Task 59 4:3 crop ("Original").

    Probes the sharpest ``count`` frames for the noun; the first frame
    with product instances and no blocking face wins. Returns [] (no
    photo) when no frame qualifies: never a centre crop for automatic
    photos.
    """
    ranked = window_frames(frames, picked)
    seen: set[str] = set()
    distinct = []
    for frame in ranked:
        key = str(frame.path)
        if key not in seen:
            seen.add(key)
            distinct.append(frame)
    chosen = _choose_frame(distinct[:max(count, 1)], noun, ledger=ledger,
                           settings=settings)
    if chosen is None:
        return []
    frame, cluster = chosen
    boxes = [inst.box for inst in cluster]
    original = crop_to_boxes(
        frame.path, boxes, out_stem.parent / f"{out_stem.name}{ORIGINAL_SUFFIX}.jpg")
    try:
        cut = cutout_from_instances(
            frame.path, cluster,
            out_stem.parent / f"{out_stem.name}{CUTOUT_SUFFIX}.jpg")
    except NoCutout:
        return [str(original)]
    return [str(cut), str(original)]
