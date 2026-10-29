"""Photo analysis engine: Spark vision lists products, SAM counts items.

Prices never come from photos. Counts are estimates the seller confirms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from app.market.search import SYNONYMS
from app.meta.sam import find_boxes
from app.meta.spark import chat_json, image_part
from app.models import Box

MIN_BOX_CONFIDENCE = 0.8

QUALITIES = ("good", "dark", "blurry", "too far")

_INSTRUCTION = (
    "Look at this market-stall photo and list each distinct fresh produce "
    "product visible. For each give: name_en (the common English name, lower "
    "case), name_local (the local name, or null unless it is obvious), "
    "countable (true if the items can be counted one by one, false for heaps "
    "of tiny items or loose leaves), visible_count (the clearly visible whole "
    "or mostly-visible items, or null if not countable), condition (one short "
    "phrase about freshness if visible, else null). Also give photo_quality, "
    "one of good, dark, blurry or too far. Do not guess any prices."
)

_CONTRACT = (
    '{"products": [{"name_en": "tomato", "name_local": null, "countable": true,'
    ' "visible_count": 12, "condition": "looks fresh"}],'
    ' "photo_quality": "good"}'
)


@dataclass
class DetectedProduct:
    name_en: str
    name_local: str | None = None
    countable: bool = False
    count_spark: int | None = None
    count_sam: int | None = None
    count: int | None = None
    count_range: tuple[int, int] | None = None
    needs_check: bool = False
    boxes: list[Box] = field(default_factory=list)
    condition: str | None = None


@dataclass
class Suggestion:
    kind: str
    text: str
    item_name: str | None = None
    action: str | None = None
    value: int | None = None


@dataclass
class PhotoReport:
    products: list[DetectedProduct] = field(default_factory=list)
    quality: str = "good"
    suggestions: list[Suggestion] = field(default_factory=list)
    cost_usd: float = 0.0


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            return None
        value = int(text)
    if not isinstance(value, int) or value < 0:
        return None
    return value


def _text_or_none(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _parse_products(data: dict) -> list[dict]:
    products: list[dict] = []
    raw_list = data.get("products") or []
    if not isinstance(raw_list, list):
        return []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        name_en = _text_or_none(raw.get("name_en"))
        if name_en is None:
            continue
        countable = raw.get("countable") is True
        visible = _int_or_none(raw.get("visible_count")) if countable else None
        products.append({
            "name_en": name_en.lower(),
            "name_local": _text_or_none(raw.get("name_local")),
            "countable": countable,
            "visible_count": visible,
            "condition": _text_or_none(raw.get("condition")),
        })
    return products


def _products_summary(data: dict) -> str:
    raw = data.get("products")
    count = len(raw) if isinstance(raw, list) else 0
    noun = "product" if count == 1 else "products"
    return f"{count} {noun}"


def list_products(image: Path, *, ledger, settings) -> tuple[list[dict], str]:
    """One Spark vision call listing the products visible in the photo."""
    messages = [{"role": "user", "content": [
        {"type": "text",
         "text": f"{_INSTRUCTION}\n\nReturn only JSON shaped like: {_CONTRACT}"},
        image_part(Path(image)),
    ]}]
    data = chat_json(messages, ledger=ledger, settings=settings,
                     reasoning_effort="low", step="scan photo",
                     summary=_products_summary)
    if not isinstance(data, dict):
        return ([], "good")
    quality = data.get("photo_quality")
    quality = quality if quality in QUALITIES else "good"
    return (_parse_products(data), quality)


def drop_low_confidence(boxes: list[Box],
                        min_confidence: float = MIN_BOX_CONFIDENCE) -> list[Box]:
    """Drop boxes below the confidence floor; unknown confidence is kept."""
    return [box for box in boxes
            if box.confidence is None or box.confidence >= min_confidence]


def _area(box: Box) -> int:
    return max(0, box.x2 - box.x1) * max(0, box.y2 - box.y1)


def _intersection(first: Box, second: Box) -> int:
    width = min(first.x2, second.x2) - max(first.x1, second.x1)
    height = min(first.y2, second.y2) - max(first.y1, second.y1)
    if width <= 0 or height <= 0:
        return 0
    return width * height


def dedupe_boxes(boxes: list[Box]) -> list[Box]:
    """Drop tiny boxes, then boxes mostly inside an already-kept box.

    A box under 30% of the median area goes first; then, largest first, any
    box whose intersection with a kept box covers 60% or more of its own area
    is dropped as a duplicate.
    """
    if not boxes:
        return []
    floor = 0.3 * median(_area(box) for box in boxes)
    candidates = [box for box in boxes if _area(box) >= floor]
    kept: list[Box] = []
    for box in sorted(candidates, key=_area, reverse=True):
        own = _area(box)
        if own and any(_intersection(box, other) >= 0.6 * own for other in kept):
            continue
        kept.append(box)
    return kept


def reconcile(count_spark: int | None, count_sam: int | None
              ) -> tuple[int | None, tuple[int, int] | None, bool]:
    """Merge the two counters: agree within 20%, else a range to check.

    When one counter sees nothing and the other sees items (e.g. hidden
    under something), the estimate is the non-zero count, still flagged.
    """
    if count_spark is None and count_sam is None:
        return (None, None, False)
    if count_spark is None:
        return (count_sam, None, False)
    if count_sam is None:
        return (count_spark, None, False)
    larger = max(count_spark, count_sam)
    if larger == 0:
        return (0, None, False)
    if min(count_spark, count_sam) == 0:
        return (larger, None, True)
    if abs(count_spark - count_sam) <= 0.2 * larger:
        return (round((count_spark + count_sam) / 2), None, False)
    return (None, (min(count_spark, count_sam), max(count_spark, count_sam)), True)


def _canonical(name: str) -> str:
    key = (name or "").strip().lower()
    return SYNONYMS.get(key, key)


def _shop_name(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("name_en", "")
    return getattr(item, "name_en", "")


def _shop_sold_out(item) -> bool:
    if isinstance(item, dict):
        return bool(item.get("sold_out", False))
    if isinstance(item, str):
        return False
    return bool(getattr(item, "sold_out", False))


def _shop_key(item) -> str:
    if isinstance(item, dict):
        return str(item.get("match_key") or item.get("name_en", ""))
    if isinstance(item, str):
        return item
    return str(getattr(item, "match_key", None)
               or getattr(item, "name_en", ""))


def _find_shop_item(name_en: str, shop_items) -> object | None:
    want = _canonical(name_en)
    for item in shop_items or []:
        if _canonical(_shop_name(item)) == want:
            return item
        if _canonical(_shop_key(item)) == want:
            return item
    return None


def _display(name_en: str) -> str:
    return name_en[:1].upper() + name_en[1:] if name_en else name_en


def analyse_photo(image: Path, *, shop_items, ledger, settings) -> PhotoReport:
    """List products with Spark, count each countable one with SAM, suggest."""
    spent_before = ledger.today_usd("meta")
    products_raw, quality = list_products(image, ledger=ledger, settings=settings)
    products: list[DetectedProduct] = []
    suggestions: list[Suggestion] = []
    if quality != "good":
        suggestions.append(Suggestion(
            kind="retake",
            text=f"Photo looks {quality}. Take it again closer, in good light."))
    for raw in products_raw:
        name_en = raw["name_en"]
        boxes: list[Box] = []
        count_sam: int | None = None
        if raw["countable"]:
            found = find_boxes(Path(image), name_en, ledger=ledger,
                               settings=settings, step="count items")
            boxes = dedupe_boxes(drop_low_confidence(found))
            count_sam = len(boxes)
        count, count_range, needs_check = reconcile(raw["visible_count"],
                                                    count_sam)
        products.append(DetectedProduct(
            name_en=name_en, name_local=raw["name_local"],
            countable=raw["countable"], count_spark=raw["visible_count"],
            count_sam=count_sam, count=count, count_range=count_range,
            needs_check=needs_check, boxes=boxes, condition=raw["condition"]))
        shop_item = _find_shop_item(name_en, shop_items)
        if shop_item is None:
            suggestions.append(Suggestion(
                kind="add_price", item_name=name_en, action="voice_update",
                text=f"{_display(name_en)} is not on your price list."
                     " Say its price to add it."))
        elif _shop_sold_out(shop_item):
            suggestions.append(Suggestion(
                kind="back_on_sale", item_name=name_en, action="unsold",
                text=f"{_display(name_en)} is in the photo but marked sold out."
                     " Put it back on sale?"))
        if needs_check and count_range is not None:
            low, high = count_range
            suggestions.append(Suggestion(
                kind="check_count", item_name=name_en, action="set_stock",
                text=f"{_display(name_en)}: we counted between {low} and {high}."
                     " Please check."))
        elif raw["countable"] and count is not None:
            suggestions.append(Suggestion(
                kind="set_stock", item_name=name_en, action="set_stock",
                value=count,
                text=f"About {count} {name_en} visible."
                     " Save as today's stock?"))
    return PhotoReport(products=products, quality=quality,
                       suggestions=suggestions,
                       cost_usd=ledger.today_usd("meta") - spent_before)
