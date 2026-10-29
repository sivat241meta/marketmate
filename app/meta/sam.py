from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

import httpx
from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMask,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
)

from app.config import META_BASE_URL, SAM_MODEL, Settings
from app.costs import CostLedger
from app.models import Box

SAM_USD_PER_IMAGE = 0.0025

_BOX_RE = re.compile(r"<\|box;([^|]*)\|>")
_MASK_RE = re.compile(r"<\|mask;([^|]*)\|>")
_MASK_DATA_RE = re.compile(r"(\d+),(\d+),([!~].*)")
_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class SamError(Exception):
    pass


@dataclass
class SamMask:
    """One decoded SAM mask, box-local: placed at its box's (x1, y1)."""

    width: int
    height: int
    encoding: str  # "one_bit" or "lossless"
    payload: str  # wire payload including the leading ! or ~ marker
    confidence: float | None = None
    _raster: bytes | None = field(default=None, repr=False, compare=False)

    def raster(self) -> bytes:
        """Row-major 0/1 bytes, ``height * width`` long (official decoder)."""
        if self._raster is None:
            try:
                record = SegmentationMask(
                    encoding=self.encoding, payload=self.payload,
                    width=self.width, height=self.height)
                self._raster = bytes(decode_mask_to_raster(record))
            except Exception as exc:
                raise SamError(f"bad SAM mask: {exc}") from exc
        return self._raster


@dataclass
class SamInstance:
    """One detected instance: a box plus its mask (None when missing)."""

    box: Box
    mask: SamMask | None = None


def parse_sam_text(text: str) -> list[Box]:
    """Parse <|box;...|> tokens by key; ignore masks and frame markers."""
    boxes: list[Box] = []
    for match in _BOX_RE.finditer(text or ""):
        fields: dict[str, str] = {}
        for part in match.group(1).split(";"):
            if "=" in part:
                key, _, value = part.partition("=")
                fields[key.strip()] = value.strip()
        try:
            confidence = float(fields["c"]) if "c" in fields else None
        except ValueError:
            confidence = None
        try:
            boxes.append(Box(
                x1=int(fields["x1"]), y1=int(fields["y1"]),
                x2=int(fields["x2"]), y2=int(fields["y2"]),
                w=int(fields["w"]), h=int(fields["h"]),
                confidence=confidence))
        except (KeyError, ValueError):
            continue
    return boxes


def _mask_from_record(mask: SegmentationMask,
                      confidence: float | None) -> SamMask:
    return SamMask(width=mask.width, height=mask.height,
                   encoding=mask.encoding, payload=mask.payload,
                   confidence=confidence)


def _parse_strict(text: str) -> list[SamInstance]:
    """Boxes and masks via Meta's official record parser.

    Returns [] when the strict grammar accepts no boxes, so the caller
    can fall back to the lenient parse below.
    """
    try:
        parser = image_segmentation_format().create_parser()
        parser.push(text or "")
        result = parser.finish(CompletedOutcome()).result
    except Exception:  # noqa: BLE001 - corrupt wire text uses lenient parse
        return []
    box_records = [record for record in result.records
                   if isinstance(record, SegmentationBoxRecord)]
    if not box_records:
        return []
    masks_by_id: dict[str, list[SegmentationMaskRecord]] = {}
    for record in result.records:
        if isinstance(record, SegmentationMaskRecord):
            masks_by_id.setdefault(record.object_id, []).append(record)
    # The strict records drop the frame size, so recover w/h from the same
    # tokens via the lenient box parse (same text, same order).
    sizes: dict[tuple[int, int, int, int], list[tuple[int, int]]] = {}
    for box in parse_sam_text(text):
        sizes.setdefault((box.x1, box.y1, box.x2, box.y2), []).append(
            (box.w, box.h))
    instances = []
    for record in box_records:
        # Strict bounds are half-open; our Box keeps the wire's x2/y2.
        coords = (int(record.left), int(record.top),
                  int(record.right) - 1, int(record.bottom) - 1)
        queue = sizes.get(coords, [])
        width, height = queue.pop(0) if queue else (0, 0)
        box = Box(*coords, width, height, record.confidence)
        mask_record = None
        pending = masks_by_id.get(record.object_id, [])
        if pending:
            mask_record = pending.pop(0)
        mask = (_mask_from_record(mask_record.mask, mask_record.confidence)
                if mask_record is not None else None)
        instances.append(SamInstance(box=box, mask=mask))
    return instances


def _parse_lenient(text: str) -> list[SamInstance]:
    """Boxes plus order-paired masks for fragments the strict grammar rejects
    (box-only text, synthetic test masks)."""
    masks: list[SamMask] = []
    for match in _MASK_RE.finditer(text or ""):
        fields: dict[str, str] = {}
        for part in match.group(1).split(";"):
            if "=" in part:
                key, _, value = part.partition("=")
                fields[key.strip()] = value.strip()
        data = _MASK_DATA_RE.match(fields.get("data", ""))
        if data is None:
            continue
        try:
            confidence = float(fields["c"]) if "c" in fields else None
        except ValueError:
            confidence = None
        payload = data.group(3)
        masks.append(SamMask(
            width=int(data.group(2)), height=int(data.group(1)),
            encoding="one_bit" if payload.startswith("!") else "lossless",
            payload=payload, confidence=confidence))
    boxes = parse_sam_text(text)
    return [SamInstance(box=box, mask=masks[pos] if pos < len(masks) else None)
            for pos, box in enumerate(boxes)]


def parse_sam_response(text: str) -> list[SamInstance]:
    """Boxes with their masks: strict official parse, lenient fallback."""
    return _parse_strict(text) or _parse_lenient(text)


def _data_url(path: Path) -> str:
    path = Path(path)
    mime = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _request_text(image: Path, noun: str, *, ledger: CostLedger,
                  settings: Settings, detail: str,
                  step: str | None = None,
                  shop_id: int | None = None,
                  session_id: int | None = None,
                  summarize: Callable[[str], str | None] | None = None,
                  ) -> str:
    """One SAM 3.1 call; returns the joined streamed text and logs cost."""
    ledger.check()
    body = {
        "model": SAM_MODEL,
        "stream": True,
        "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": noun},
            {"type": "input_image", "image_url": _data_url(image)},
        ]}],
    }
    chunks: list[str] = []
    started = monotonic()
    try:
        with httpx.stream("POST", f"{META_BASE_URL}/responses", json=body,
                           headers={"Authorization": "Bearer " + settings.model_api_key},
                           timeout=180.0) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "response.output_text.delta":
                    chunks.append(event.get("delta", ""))
                if event.get("type") == "response.completed":
                    break
    except Exception as exc:
        ledger.add("meta", SAM_MODEL, 0.0, detail,
                   shop_id=shop_id, session_id=session_id, step=step,
                   latency_ms=int((monotonic() - started) * 1000), ok=0)
        raise SamError(f"SAM request failed: {exc}") from exc
    text = "".join(chunks)
    summary = None
    if summarize is not None:
        try:
            summary = summarize(text)
        except Exception:  # noqa: BLE001 - a bad summary never fails the call
            summary = None
    ledger.add("meta", SAM_MODEL, SAM_USD_PER_IMAGE, detail,
               shop_id=shop_id, session_id=session_id, step=step,
               latency_ms=int((monotonic() - started) * 1000), ok=1,
               summary=summary)
    return text


def _box_summary(text: str) -> str:
    boxes = parse_sam_text(text)
    return _with_confidence(f"{len(boxes)} boxes",
                            [b.confidence for b in boxes])


def _mask_summary(text: str) -> str:
    instances = parse_sam_response(text)
    masks = sum(1 for inst in instances if inst.mask is not None)
    return _with_confidence(f"{masks} masks",
                            [inst.mask.confidence for inst in instances
                             if inst.mask is not None])


def _with_confidence(base: str, confidences: list[float | None]) -> str:
    known = [c for c in confidences if c is not None]
    if not known:
        return base
    return f"{base} c={sum(known) / len(known):.2f}"


def find_boxes(image: Path, noun: str, *, ledger: CostLedger, settings: Settings,
               detail: str = "find_boxes",
               step: str | None = None,
               shop_id: int | None = None,
               session_id: int | None = None) -> list[Box]:
    """Segment every instance of noun in image via SAM 3.1; log cost."""
    return parse_sam_text(_request_text(
        image, noun, ledger=ledger, settings=settings, detail=detail,
        step=step, shop_id=shop_id, session_id=session_id,
        summarize=_box_summary))


def find_instances(image: Path, noun: str, *, ledger: CostLedger,
                   settings: Settings, detail: str = "find_instances",
                   step: str | None = None,
                   shop_id: int | None = None,
                   session_id: int | None = None,
                   ) -> list[SamInstance]:
    """Like find_boxes, but each box keeps its decoded mask."""
    return parse_sam_response(_request_text(
        image, noun, ledger=ledger, settings=settings, detail=detail,
        step=step, shop_id=shop_id, session_id=session_id,
        summarize=_mask_summary))
