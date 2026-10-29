from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageStat

from app.costs import CostCapExceeded
from app.meta.sam import SamError, SamInstance, find_boxes, find_instances
from app.meta.spark import chat_json, image_part
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
#: Task 67: whole objects only. A box within this frame fraction of any
#: edge is cut off; mask components under this fraction of the main
#: instance's area are slivers; neighbours must touch the main one, be
#: whole, and pass these confidence and area gates (at most two).
#: Task 72: neighbours also pass the whole-object shape test (solidity
#: and box aspect close to the main instance) and the area gate is 60%.
EDGE_MARGIN = 0.02
SLIVER_FRACTION = 0.04
NEIGHBOUR_CONFIDENCE = 0.45
NEIGHBOUR_AREA_FRACTION = 0.60
MAX_NEIGHBOURS = 2
#: Task 72: mask area / convex-hull area floor for a whole object, and
#: the box aspect-ratio tolerance against the main instance (a tall thin
#: half slice next to round fruit is ~2x off and fails).
SOLIDITY_FLOOR = 0.88
ASPECT_TOLERANCE = 1.5
#: Task 72: generic fallback. Items whose nouns found nothing are
#: re-queried once with their category noun ("fruit"/"vegetable", or
#: "produce" when unknown); up to this many instances at or above this
#: confidence go to the single Spark verification.
FALLBACK_CONFIDENCE = 0.4
MAX_FALLBACK_CANDIDATES = 4
PRODUCE_NOUN = "produce"
#: Task 67: a target instance whose mask overlaps another item's instance
#: by this IoU or more, with the other noun more confident, is dropped.
CROSS_IOU = 0.5
#: Task 67: per-item budget (SAM calls) and cross-check scope: at most two
#: extra nouns, from items whose picked frame is within ±2 s or the same
#: picture.
MAX_SAM_PER_ITEM = 6
MAX_OTHER_NOUNS = 2
SHARE_WINDOW_MS = 2000
#: Task 67: post-resize alpha feather radius, in pixels.
FEATHER_RADIUS = 1.5


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


def _mask_raster_at(inst: SamInstance) -> tuple[bytes, int, int] | None:
    """Decoded (raster, width, height), None when the mask is unusable."""
    if inst.mask is None:
        return None
    try:
        raster = bytes(inst.mask.raster())
    except SamError:
        return None
    if len(raster) != inst.mask.width * inst.mask.height:
        return None
    return raster, inst.mask.width, inst.mask.height


def _mask_iou(first: SamInstance, second: SamInstance) -> float | None:
    """IoU of the two masks placed at their boxes, None when unusable."""
    decoded = (_mask_raster_at(first), _mask_raster_at(second))
    if decoded[0] is None or decoded[1] is None:
        return None
    (raster_a, wa, ha), (raster_b, wb, hb) = decoded
    left = max(first.box.x1, second.box.x1)
    top = max(first.box.y1, second.box.y1)
    right = min(first.box.x2, second.box.x2)
    bottom = min(first.box.y2, second.box.y2)
    if right < left or bottom < top:
        return 0.0
    inter = 0
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            ax, ay = x - first.box.x1, y - first.box.y1
            bx, by = x - second.box.x1, y - second.box.y1
            if (0 <= ax < wa and 0 <= ay < ha and raster_a[ay * wa + ax]
                    and 0 <= bx < wb and 0 <= by < hb
                    and raster_b[by * wb + bx]):
                inter += 1
    union = sum(raster_a) + sum(raster_b) - inter
    return inter / union if union else None


def instances_iou(first: SamInstance, second: SamInstance) -> float:
    """Mask IoU of two instances, falling back to box IoU without masks."""
    iou = _mask_iou(first, second)
    if iou is not None:
        return iou
    left = max(first.box.x1, second.box.x1)
    top = max(first.box.y1, second.box.y1)
    right = min(first.box.x2, second.box.x2)
    bottom = min(first.box.y2, second.box.y2)
    inter = max(right - left + 1, 0) * max(bottom - top + 1, 0)
    if not inter:
        return 0.0
    union = _box_area(first.box) + _box_area(second.box) - inter
    return inter / union if union else 0.0


def _more_confident(other: SamInstance, target: SamInstance) -> bool:
    """True when the other instance is strictly more confident.

    A missing confidence never decides: the comparison needs both.
    """
    mine, theirs = target.box.confidence, other.box.confidence
    return (mine is not None and theirs is not None and theirs > mine)


def drop_confused(targets: list[SamInstance],
                  others: list[SamInstance]) -> list[SamInstance]:
    """Drop target instances that are really another item (Task 67).

    A target instance goes when another noun's instance overlaps it by
    IoU ≥ 0.5 with the higher confidence.
    """
    kept = []
    for target in targets:
        confused = any(
            _more_confident(other, target)
            and instances_iou(target, other) >= CROSS_IOU
            for other in others)
        if not confused:
            kept.append(target)
    return kept


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


def touches_edge(box: Box, width: int, height: int) -> bool:
    """True when the box is cut off by the frame (within 2% of any edge)."""
    margin_x, margin_y = EDGE_MARGIN * width, EDGE_MARGIN * height
    return (box.x1 < margin_x or box.y1 < margin_y
            or box.x2 > width - 1 - margin_x
            or box.y2 > height - 1 - margin_y)


def mask_ones(inst: SamInstance) -> int | None:
    """Foreground pixel count of the instance's mask, None when missing."""
    if inst.mask is None:
        return None
    try:
        return sum(inst.mask.raster())
    except SamError:
        return None


def instance_area(inst: SamInstance) -> int:
    """Mask pixel area when the mask decodes, else the box area."""
    return mask_ones(inst) or _box_area(inst.box)


def _boundary_points(raster: bytes, width: int, height: int,
                     ) -> list[tuple[int, int]]:
    """Foreground pixels with a background (or out-of-frame) 4-neighbour."""
    points = []
    for y in range(height):
        row = y * width
        for x in range(width):
            if not raster[row + x]:
                continue
            if (x == 0 or y == 0 or x == width - 1 or y == height - 1
                    or not raster[row + x - 1] or not raster[row + x + 1]
                    or not raster[row - width + x]
                    or not raster[row + width + x]):
                points.append((x, y))
    return points


def _convex_hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Monotone-chain convex hull of lattice points, CCW, no duplicate end."""
    corners = sorted(set(points))
    if len(corners) <= 1:
        return corners

    def cross(origin, first, second):
        return ((first[0] - origin[0]) * (second[1] - origin[1])
                - (first[1] - origin[1]) * (second[0] - origin[0]))

    lower: list[tuple[int, int]] = []
    for point in corners:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[int, int]] = []
    for point in reversed(corners):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _hull_pixel_area(hull: list[tuple[int, int]]) -> float:
    """Lattice-polygon pixel count via Pick's theorem (area + b/2 + 1)."""
    area = 0
    girth = 0.0
    for pos, (x, y) in enumerate(hull):
        nx, ny = hull[(pos + 1) % len(hull)]
        area += x * ny - nx * y
        girth += ((nx - x) ** 2 + (ny - y) ** 2) ** 0.5
    return abs(area) / 2 + girth / 2 + 1


def mask_solidity(inst: SamInstance) -> float | None:
    """Mask area / convex-hull area, None when the mask is missing.

    A whole round fruit fills its hull (~1.0); a half slice cut by a
    container wall leaves a concave bite well under the floor.
    """
    decoded = _mask_raster_at(inst)
    if decoded is None:
        return None
    raster, width, height = decoded
    area = sum(raster)
    if not area:
        return None
    hull = _convex_hull(_boundary_points(raster, width, height))
    if len(hull) < 3:
        return 1.0
    whole = _hull_pixel_area(hull)
    if whole <= 0:
        return 1.0
    return min(area / whole, 1.0)


def _solidity_ok(inst: SamInstance) -> bool:
    """True when the mask looks whole; a missing mask never filters."""
    solidity = mask_solidity(inst)
    return solidity is None or solidity >= SOLIDITY_FLOOR


def _box_aspect(box: Box) -> float:
    """Box width / height, at least 1px each side."""
    return (max(box.x2 - box.x1 + 1, 1)
            / max(box.y2 - box.y1 + 1, 1))


def _aspect_close(main_aspect: float, other_aspect: float) -> bool:
    """True when the two aspects agree within ``ASPECT_TOLERANCE``."""
    if main_aspect <= 0 or other_aspect <= 0:
        return False
    return max(main_aspect, other_aspect) / min(main_aspect, other_aspect) \
        <= ASPECT_TOLERANCE


def _neighbours_8(x: int, y: int, width: int, height: int):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    yield ny * width + nx


def _label_foreground(raster: bytes, width: int, height: int,
                      ) -> tuple[list[int], dict[int, int]]:
    """8-connected foreground labels and {label: pixel count} sizes."""
    labels = [0] * (width * height)
    sizes: dict[int, int] = {}
    current = 0
    for pos, bit in enumerate(raster):
        if not bit or labels[pos]:
            continue
        current += 1
        size = 0
        stack = [pos]
        labels[pos] = current
        while stack:
            cell = stack.pop()
            size += 1
            x, y = cell % width, cell // width
            for nxt in _neighbours_8(x, y, width, height):
                if raster[nxt] and not labels[nxt]:
                    labels[nxt] = current
                    stack.append(nxt)
        sizes[current] = size
    return labels, sizes


def _fill_small_holes(bits: bytearray, width: int, height: int,
                      min_area: int) -> None:
    """Fill interior background regions smaller than ``min_area`` in place.

    The background reachable from the border (4-connected) stays; the
    rest is holes.
    """
    reached = bytearray(width * height)
    stack = [x for x in range(width) if not bits[x]]
    stack += [x for x in range((height - 1) * width, width * height)
              if not bits[x]]
    stack += [y * width for y in range(height) if not bits[y * width]]
    stack += [(y + 1) * width - 1 for y in range(height)
              if not bits[(y + 1) * width - 1]]
    for pos in stack:
        reached[pos] = 1
    while stack:
        cell = stack.pop()
        x, y = cell % width, cell // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                nxt = ny * width + nx
                if not bits[nxt] and not reached[nxt]:
                    reached[nxt] = 1
                    stack.append(nxt)
    for pos in range(width * height):
        if bits[pos] or reached[pos]:
            continue
        hole = [pos]
        reached[pos] = 1
        stack = [pos]
        while stack:
            cell = stack.pop()
            x, y = cell % width, cell // width
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height:
                    nxt = ny * width + nx
                    if not bits[nxt] and not reached[nxt]:
                        reached[nxt] = 1
                        hole.append(nxt)
                        stack.append(nxt)
        if len(hole) < min_area:
            for cell in hole:
                bits[cell] = 1


def clean_raster(raster: bytes, width: int, height: int,
                 main_area: int) -> bytes:
    """Only the largest component kept; small holes filled.

    Every other component is a sliver of neighbouring fruit and goes
    (anything under 4% of the main area most of all). Interior holes
    under 4% of the main area are filled.
    """
    if len(raster) != width * height:
        return raster
    labels, sizes = _label_foreground(raster, width, height)
    if not sizes:
        return bytes(raster)
    floor = max(1, round(SLIVER_FRACTION * main_area))
    biggest = max(sizes, key=lambda label: sizes[label])
    bits = bytearray(width * height)
    for pos, label in enumerate(labels):
        if label == biggest:
            bits[pos] = 1
    _fill_small_holes(bits, width, height, floor)
    return bytes(bits)


def _score(inst: SamInstance) -> float:
    """Ranking score: confidence × sqrt(area); unknown confidence is 1."""
    confidence = inst.box.confidence if inst.box.confidence is not None else 1.0
    return confidence * instance_area(inst) ** 0.5


def select_whole(instances: list[SamInstance],
                 frame_size: tuple[int, int]) -> list[SamInstance]:
    """Main-first cluster of whole instances only (Task 67).

    Edge-touching instances are dropped whenever a whole one exists, and
    a cut-off object is never the main one: with no whole instance there
    is no cluster. The main instance maximises confidence × sqrt(area);
    up to two neighbours join it when they touch or overlap it, are
    whole, and pass the 0.45 confidence and 60%-of-main-area gates.

    Task 72: every neighbour also passes the whole-object shape test
    (solidity ≥ 0.88 and box aspect within ×1.5 of the main instance),
    and the main one defers to the best solid candidate when one exists.
    """
    width, height = frame_size
    whole = [inst for inst in instances
             if not touches_edge(inst.box, width, height)]
    if not whole:
        return []
    solid = [inst for inst in whole if _solidity_ok(inst)]
    main = max(solid or whole, key=_score)
    floor = NEIGHBOUR_AREA_FRACTION * instance_area(main)
    main_aspect = _box_aspect(main.box)
    neighbours = [
        inst for inst in sorted(whole, key=_score, reverse=True)
        if inst is not main
        and _passes(inst.box.confidence, NEIGHBOUR_CONFIDENCE)
        and instance_area(inst) >= floor
        and _touches(main.box, inst.box)
        and _solidity_ok(inst)
        and _aspect_close(main_aspect, _box_aspect(inst.box))]
    return [main, *neighbours[:MAX_NEIGHBOURS]]


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


def _erase_islands(matte: Image.Image, seeds: list[tuple[int, int]]
                   ) -> Image.Image:
    """Keep only matte foreground connected (8-way) to a seed pixel."""
    width, height = matte.size
    pixels = matte.load()
    kept = Image.new("L", matte.size, 0)
    out = kept.load()
    seen = bytearray(width * height)
    stack = [(x, y) for x, y in seeds
             if 0 <= x < width and 0 <= y < height and pixels[x, y]]
    for x, y in stack:
        seen[y * width + x] = 1
    while stack:
        x, y = stack.pop()
        out[x, y] = 255
        for ny in (y - 1, y, y + 1):
            if not 0 <= ny < height:
                continue
            for nx in (x - 1, x, x + 1):
                if (nx, ny) == (x, y) or not 0 <= nx < width:
                    continue
                pos = ny * width + nx
                if pixels[nx, ny] and not seen[pos]:
                    seen[pos] = 1
                    stack.append((nx, ny))
    return kept


def place_masks(frame_size: tuple[int, int],
                cluster: list[SamInstance], *, clean: bool = False
                ) -> Image.Image:
    """Union of the cluster's decoded masks at their box positions.

    Each mask is box-local; when its raster differs from the box size (a
    pixel or two off), it is scaled to the box. Raises ``NoCutout`` when
    no mask decodes. With ``clean``, each mask keeps only its largest
    component (Task 67) and alpha islands unconnected to a kept
    instance are erased.
    """
    matte = Image.new("L", frame_size, 0)
    placed = 0
    seeds: list[tuple[int, int]] = []
    main_area = instance_area(cluster[0]) if clean and cluster else 0
    for inst in cluster:
        if inst.mask is None:
            continue
        try:
            raster = inst.mask.raster()
        except SamError:
            continue
        if clean:
            raster = clean_raster(bytes(raster), inst.mask.width,
                                  inst.mask.height, main_area)
            try:
                first = raster.index(1)
            except ValueError:
                continue
            want_w = max(inst.box.x2 - inst.box.x1 + 1, 1)
            want_h = max(inst.box.y2 - inst.box.y1 + 1, 1)
            seeds.append((
                inst.box.x1 + round(first % inst.mask.width
                                    * want_w / inst.mask.width),
                inst.box.y1 + round(first // inst.mask.width
                                    * want_h / inst.mask.height)))
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
    if clean:
        matte = _erase_islands(matte, seeds)
    return matte


def defringe(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Drop dark old-background pixels caught along the matte edge.

    Pixels with partial alpha that are very dark (fringe from the
    removed background) go fully transparent.
    """
    edge = alpha.point(lambda value: 255 if 8 < value < 200 else 0)
    dark = rgb.convert("L").point(lambda value: 255 if value < 60 else 0)
    fringe = ImageChops.darker(edge, dark)  # both are 0/255: min() is AND
    return ImageChops.subtract(alpha, fringe)


def cutout_from_instances(image: Path, cluster: list[SamInstance],
                          out: Path, *, clean: bool = False) -> Path:
    """Quick-commerce tile: masked product on a 900×900 white canvas.

    The product fits 78% of the canvas, sits slightly low, and gets a
    soft contact shadow (blurred alpha, 6% opacity). Raises ``NoCutout``
    when no mask decodes. With ``clean``, masks are component-cleaned
    (Task 67), the edge is defringed, and the alpha gets a 1–2 px
    feather.
    """
    with Image.open(image) as img:
        rgb = img.convert("RGB")
    matte = place_masks(rgb.size, cluster, clean=clean).filter(
        ImageFilter.GaussianBlur(1.5))
    bounds = matte.getbbox()
    if bounds is None:  # pragma: no cover - place_masks guarantees pixels
        raise NoCutout("empty matte")
    tight = rgb.crop(bounds)
    alpha = matte.crop(bounds)
    if clean:
        alpha = defringe(tight, alpha)
    scale = CUTOUT_SIZE * CUTOUT_FIT / max(tight.size)
    size = (max(1, round(tight.width * scale)),
            max(1, round(tight.height * scale)))
    tight = tight.resize(size, Image.LANCZOS)
    alpha = alpha.resize(size, Image.LANCZOS)
    if clean:
        alpha = alpha.filter(ImageFilter.GaussianBlur(FEATHER_RADIUS))
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


class _BudgetOut(Exception):
    """The per-item SAM budget (``MAX_SAM_PER_ITEM``) is spent."""


def _sam_call(used: list[int], func, *args, **kwargs):
    """One budgeted SAM call; raises ``_BudgetOut`` past the per-item cap."""
    if used[0] >= MAX_SAM_PER_ITEM:
        raise _BudgetOut
    used[0] += 1
    return func(*args, **kwargs)


_VISUAL_NOUN_PROMPT = (
    "You sell fresh produce at an Indian market stall. For each item below, "
    "give a short visual noun: 2-3 plain English words a vision model would "
    "use for this item in a market stall photo. Also say whether it is a "
    "fruit or a vegetable in the kitchen (tomato counts as vegetable).\n"
    "Items: {items}\n\n"
    'Return only JSON shaped like: {{"{first}": '
    '{{"noun": "red tomato", "category": "vegetable"}}}}'
)


def _clean_noun(value, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    words = value.strip().split()
    if not words:
        return fallback
    return " ".join(words[:4])


def _split_noun_category(value, fallback: str) -> tuple[str, str]:
    """(visual noun, category) from one Spark answer, old or new format.

    New answers are {"noun": ..., "category": "fruit"|"vegetable"};
    old plain-string answers (and anything unrecognised) keep the noun
    and mean the category is unknown ("produce").
    """
    if isinstance(value, dict):
        noun = _clean_noun(value.get("noun"), fallback)
        category = str(value.get("category") or "").strip().lower()
        if category == "fruit" or category.startswith("veg"):
            return noun, ("fruit" if category == "fruit" else "vegetable")
        return noun, PRODUCE_NOUN
    return _clean_noun(value, fallback), PRODUCE_NOUN


def ensure_visual_nouns(names: list[str], cache: dict, *,
                        ledger, settings,
                        category_cache: dict | None = None
                        ) -> dict[str, str]:
    """Short visual noun per item, asked once per session and cached.

    One Spark text call covers every name missing from ``cache`` (the
    session's cache); cached names never re-ask. Returns
    {name: visual noun}, falling back to the name itself per item.
    Task 72: the same call also returns each item's kitchen category
    ("fruit" or "vegetable", "produce" when unknown) into
    ``category_cache`` for the generic fallback.
    """
    missing = [name for name in dict.fromkeys(names)
               if name not in cache
               or (category_cache is not None
                   and name not in category_cache)]
    if missing:
        prompt = _VISUAL_NOUN_PROMPT.format(
            items=", ".join(missing), first=missing[0])
        data = chat_json([{"role": "user", "content": prompt}],
                         ledger=ledger, settings=settings,
                         reasoning_effort="low")
        answers = data if isinstance(data, dict) else {}
        lowered = {str(key).strip().lower(): value
                   for key, value in answers.items()}
        for name in missing:
            noun, category = _split_noun_category(
                lowered.get(name.strip().lower()), name)
            cache[name] = noun
            if category_cache is not None:
                category_cache[name] = category
    return {name: cache.get(name, name) for name in names}


def generic_noun_for(name: str, category_cache: dict | None) -> str:
    """Generic SAM noun for the fallback: the cached category, else produce."""
    if category_cache is not None:
        category = str(category_cache.get(name) or "").strip().lower()
        if category in ("fruit", "vegetable"):
            return category
    return PRODUCE_NOUN


def _other_nouns(noun: str, picked: Frame,
                 picked_frames: list[tuple[str, Frame]]) -> list[str]:
    """At most two other items' nouns likely to share the picked frame.

    Candidates are other items whose picked frame is the same picture
    or within ±2 s; same-picture items come first.
    """
    want = noun.strip().lower()
    scored = []
    for name, frame in picked_frames or []:
        if name.strip().lower() == want:
            continue
        same = str(frame.path) == str(picked.path)
        delta = abs(frame.t_ms - picked.t_ms)
        if same or delta <= SHARE_WINDOW_MS:
            scored.append((not same, delta, name))
    scored.sort(key=lambda entry: (entry[0], entry[1]))
    nouns = []
    for _, _, name in scored:
        if name not in nouns:
            nouns.append(name)
        if len(nouns) >= MAX_OTHER_NOUNS:
            break
    return nouns


def verify_cutout(cutout: Path, target: str, candidates: list[str], *,
                  ledger, settings) -> str:
    """One Spark vision call: which session item does the cut-out show?

    Returns the matched item name (lower-cased) or ``"none"``.
    """
    names = [name for name in dict.fromkeys(candidates) if name]
    instruction = (
        "Look at this product cut-out photo (one product on a white "
        "background). Which ONE of these items does it show? "
        + ", ".join(names)
        + '. Reply with exactly one of the item names, or "none" if it '
        'shows something else or is unclear. Return only JSON shaped '
        'like: {"item": "tomato"}')
    data = chat_json([{"role": "user", "content": [
        {"type": "text", "text": instruction},
        image_part(Path(cutout))]}],
        ledger=ledger, settings=settings, reasoning_effort="low")
    answer = data.get("item") if isinstance(data, dict) else None
    if isinstance(answer, str) and answer.strip():
        return answer.strip().lower()
    return "none"


def candidate_montage(frame: Path, candidates: list[SamInstance],
                      out: Path, cell: int = 320) -> Path:
    """Numbered grid of the candidates' crops (1-based, left to right)."""
    with Image.open(frame) as img:
        rgb = img.convert("RGB")
    tiles = []
    for pos, inst in enumerate(candidates):
        left = min(max(inst.box.x1, 0), rgb.width - 1)
        top = min(max(inst.box.y1, 0), rgb.height - 1)
        right = min(max(inst.box.x2 + 1, left + 1), rgb.width)
        bottom = min(max(inst.box.y2 + 1, top + 1), rgb.height)
        crop = rgb.crop((left, top, right, bottom))
        crop.thumbnail((cell, cell), Image.LANCZOS)
        tile = Image.new("RGB", (cell, cell), (255, 255, 255))
        tile.paste(crop, ((cell - crop.width) // 2,
                          (cell - crop.height) // 2))
        draw = ImageDraw.Draw(tile)
        draw.text((12, 8), str(pos + 1), fill=(255, 255, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0))
        tiles.append(tile)
    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (255, 255, 255))
    for pos, tile in enumerate(tiles):
        sheet.paste(tile, ((pos % cols) * cell, (pos // cols) * cell))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=PHOTO_QUALITY)
    return out


def verify_candidates(frame: Path, target: str,
                      candidates: list[SamInstance], *,
                      ledger, settings) -> list[SamInstance]:
    """One Spark vision call: which candidates clearly show the target?

    The candidates' crops go out as one numbered image; the reply lists
    the 1-based numbers to keep ({"keep": [1, 3]}). Anything unparseable
    keeps nothing.
    """
    handle, tmp = tempfile.mkstemp(suffix=".jpg")
    try:
        os.close(handle)
        montage = candidate_montage(Path(frame), candidates, Path(tmp))
        instruction = (
            "These numbered crops come from one market-stall photo. "
            f"Which of them clearly show {target}? Reply with only JSON "
            'shaped like: {"keep": [1]}. Use an empty list when none '
            f"shows {target}.")
        data = chat_json([{"role": "user", "content": [
            {"type": "text", "text": instruction},
            image_part(montage)]}],
            ledger=ledger, settings=settings, reasoning_effort="low")
    finally:
        Path(tmp).unlink(missing_ok=True)
    keep = data.get("keep") if isinstance(data, dict) else None
    wanted: set[int] = set()
    if isinstance(keep, list):
        for entry in keep:
            try:
                number = int(str(entry).strip())
            except (TypeError, ValueError):
                continue
            if 1 <= number <= len(candidates):
                wanted.add(number - 1)
    return [inst for pos, inst in enumerate(candidates) if pos in wanted]


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


def _clean_frame_paths(out_stem: Path) -> tuple[Path, Path]:
    parent = out_stem.parent
    return (parent / f"{out_stem.name}{CUTOUT_SUFFIX}.jpg",
            parent / f"{out_stem.name}{ORIGINAL_SUFFIX}.jpg")


def _try_clean_frame(frame: Frame, nouns: list[str], others: list[str],
                     names: list[str], out_stem: Path, used: list[int], *,
                     ledger, settings) -> tuple[list[str] | None, bool]:
    """One frame's clean candidates, plus whether the nouns found anything.

    Gates in order: target instances exist, a whole cluster selects, no
    face blocks, cross-check survivors remain, the cut-out verifies as
    the target item. Without decodable masks the original 4:3 crop is
    offered alone when it still contains the target per SAM.
    """
    noun = nouns[0]
    instances: list[SamInstance] = []
    for target_noun in nouns:
        found = _sam_call(used, find_instances, frame.path, target_noun,
                          ledger=ledger, settings=settings,
                          detail=f"target:{target_noun}")
        passing = [inst for inst in found
                   if _passes(inst.box.confidence, PRODUCT_CONFIDENCE)]
        if passing:
            instances = passing
            break
    if not instances:
        return None, False
    size = _frame_size(frame.path)
    cluster = select_whole(instances, size)
    if not cluster:
        return None, True
    faces = _sam_call(used, find_boxes, frame.path, FACE_NOUN,
                      ledger=ledger, settings=settings, detail="face")
    boxes = [inst.box for inst in cluster]
    if face_blocks_frame(faces, frame_size=size,
                         crop_area=crop_box(boxes, *size),
                         cluster=cluster_box(cluster)):
        return None, True
    if others:
        rival: list[SamInstance] = []
        for other in others:
            found = _sam_call(used, find_instances, frame.path, other,
                              ledger=ledger, settings=settings,
                              detail=f"cross:{other}")
            rival.extend(inst for inst in found
                         if _passes(inst.box.confidence, PRODUCT_CONFIDENCE))
        cluster = select_whole(drop_confused(instances, rival), size)
        if not cluster:
            return None, True
        boxes = [inst.box for inst in cluster]
    cut_path, orig_path = _clean_frame_paths(out_stem)
    try:
        cutout_from_instances(frame.path, cluster, cut_path, clean=True)
    except NoCutout:
        if _intersects(cluster[0].box, crop_box(boxes, *size)):
            return [str(crop_to_boxes(frame.path, boxes, orig_path))], True
        return None, True
    try:
        answer = verify_cutout(cut_path, noun, names, ledger=ledger,
                               settings=settings)
    except CostCapExceeded:
        raise
    except Exception:  # noqa: BLE001 - a failed check fails the frame
        answer = None
    if answer != noun.strip().lower():
        cut_path.unlink(missing_ok=True)
        return None, True
    saved = [str(cut_path)]
    if _intersects(cluster[0].box, crop_box(boxes, *size)):
        saved.append(str(crop_to_boxes(frame.path, boxes, orig_path)))
    return saved, True


def _try_generic_fallback(frame: Frame, target: str, generic_noun: str,
                          out_stem: Path, used: list[int], *,
                          ledger, settings) -> list[str] | None:
    """One generic query on the best frame when the nouns found nothing.

    Up to four instances at c ≥ 0.4 go to the single Spark verification;
    the survivors go through the same whole-object, sliver, face and
    canvas rules as the normal path. None when nothing verifies.
    """
    found = _sam_call(used, find_instances, frame.path, generic_noun,
                      ledger=ledger, settings=settings,
                      detail=f"generic:{generic_noun}")
    candidates = [
        inst for inst in sorted(found, key=_score, reverse=True)
        if _passes(inst.box.confidence, FALLBACK_CONFIDENCE)
    ][:MAX_FALLBACK_CANDIDATES]
    if not candidates:
        return None
    try:
        kept = verify_candidates(frame.path, target, candidates,
                                 ledger=ledger, settings=settings)
    except CostCapExceeded:
        raise
    except Exception:  # noqa: BLE001 - a failed check fails the fallback
        return None
    if not kept:
        return None
    size = _frame_size(frame.path)
    cluster = select_whole(kept, size)
    if not cluster:
        return None
    faces = _sam_call(used, find_boxes, frame.path, FACE_NOUN,
                      ledger=ledger, settings=settings, detail="face")
    boxes = [inst.box for inst in cluster]
    if face_blocks_frame(faces, frame_size=size,
                         crop_area=crop_box(boxes, *size),
                         cluster=cluster_box(cluster)):
        return None
    cut_path, orig_path = _clean_frame_paths(out_stem)
    try:
        cutout_from_instances(frame.path, cluster, cut_path, clean=True)
    except NoCutout:
        if _intersects(cluster[0].box, crop_box(boxes, *size)):
            return [str(crop_to_boxes(frame.path, boxes, orig_path))]
        return None
    saved = [str(cut_path)]
    if _intersects(cluster[0].box, crop_box(boxes, *size)):
        saved.append(str(crop_to_boxes(frame.path, boxes, orig_path)))
    return saved


def _make_candidates_clean(frames: list[Frame], picked: Frame, noun: str,
                           out_stem: Path, names: list[str],
                           picked_frames, noun_cache: dict | None,
                           category_cache: dict | None, *,
                           ledger, settings, count: int) -> list[str]:
    """Task 67 candidates: whole objects, cross-checked, Spark-verified.

    Tries the English name first, then the session's visual noun; tries
    frames sharpest-first and stops at the first cut-out that verifies
    as the target. At most ``MAX_SAM_PER_ITEM`` SAM calls; [] (letter
    tile) when no frame passes every gate. Task 72: when the nouns find
    nothing on the best frame, one generic query on that frame plus the
    single Spark verification gets a second chance.
    """
    try:
        visual = ensure_visual_nouns(
            names, noun_cache if noun_cache is not None else {},
            ledger=ledger, settings=settings,
            category_cache=category_cache).get(noun, noun)
    except CostCapExceeded:
        raise
    except Exception:  # noqa: BLE001 - nouns fall back to English
        visual = noun
    nouns = [noun]
    if visual.strip().lower() not in ("", noun.strip().lower()):
        nouns.append(visual.strip())
    ranked = window_frames(frames, picked)
    seen: set[str] = set()
    distinct = []
    for frame in ranked:
        key = str(frame.path)
        if key not in seen:
            seen.add(key)
            distinct.append(frame)
    others = _other_nouns(noun, picked, picked_frames)
    generic = generic_noun_for(noun, category_cache)
    used = [0]
    first = True
    for frame in distinct[:max(count, 1)]:
        try:
            saved, found = _try_clean_frame(
                frame, nouns, others, names, out_stem,
                used, ledger=ledger, settings=settings)
        except _BudgetOut:
            return []
        if saved is not None:
            return saved
        if first and not found:
            try:
                fallback = _try_generic_fallback(
                    frame, noun, generic, out_stem, used,
                    ledger=ledger, settings=settings)
            except _BudgetOut:
                return []
            if fallback is not None:
                return fallback
        first = False
    return []


def make_candidates(frames: list[Frame], picked: Frame, noun: str,
                    out_stem: Path, *, ledger, settings,
                    count: int = 3, session_items=None,
                    picked_frames=None, noun_cache=None,
                    category_cache=None) -> list[str]:
    """Cut-out (default) plus the Task 59 4:3 crop ("Original").

    Probes the sharpest ``count`` frames for the noun; the first frame
    with product instances and no blocking face wins. Returns [] (no
    photo) when no frame qualifies: never a centre crop for automatic
    photos. With ``session_items`` (Task 67), whole objects only,
    cross-checked against the session's other items and Spark-verified.
    ``category_cache`` (Task 72) feeds the generic fallback.
    """
    if session_items is not None:
        return _make_candidates_clean(
            frames, picked, noun, out_stem, list(session_items),
            picked_frames, noun_cache, category_cache,
            ledger=ledger, settings=settings, count=count)
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
