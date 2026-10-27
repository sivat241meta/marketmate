from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import httpx

from app.config import META_BASE_URL, SAM_MODEL, Settings
from app.costs import CostLedger
from app.models import Box

SAM_USD_PER_IMAGE = 0.0025

_BOX_RE = re.compile(r"<\|box;([^|]*)\|>")
_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class SamError(Exception):
    pass


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
            boxes.append(Box(
                x1=int(fields["x1"]), y1=int(fields["y1"]),
                x2=int(fields["x2"]), y2=int(fields["y2"]),
                w=int(fields["w"]), h=int(fields["h"]), confidence=None))
        except (KeyError, ValueError):
            continue
    return boxes


def _data_url(path: Path) -> str:
    path = Path(path)
    mime = _MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def find_boxes(image: Path, noun: str, *, ledger: CostLedger, settings: Settings) -> list[Box]:
    """Segment every instance of noun in image via SAM 3.1; log cost."""
    ledger.check()
    body = {
        "model": SAM_MODEL,
        "stream": True,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": noun},
            {"type": "input_image", "image_url": _data_url(image)},
        ]}],
    }
    chunks: list[str] = []
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
        raise SamError(f"SAM request failed: {exc}") from exc
    ledger.add("meta", SAM_MODEL, SAM_USD_PER_IMAGE, "find_boxes")
    return parse_sam_text("".join(chunks))
