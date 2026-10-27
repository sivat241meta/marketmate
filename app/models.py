from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

UNITS = ("kg", "g", "piece", "dozen", "bunch", "packet")


@dataclass
class Turn:
    id: int
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Transcript:
    text: str
    duration_ms: int
    turns: list[Turn]


@dataclass
class Frame:
    path: Path
    t_ms: int


@dataclass
class PriceLine:
    price: Decimal | None
    per_amount: Decimal | None
    unit: str | None
    said: str = ""


@dataclass
class Proof:
    quote: str
    turn_ids: list[int]
    start_ms: int
    end_ms: int
    frame: str | None = None
    audio_clip: str | None = None


@dataclass
class Flag:
    field: str
    code: str
    message: str
    options: list[str] = field(default_factory=list)
    blocking: bool = True


@dataclass
class DraftItem:
    name_spoken: str
    name_ta: str
    name_en: str
    variety: str | None
    price_lines: list[PriceLine]
    qty: Decimal | None
    qty_unit: str | None
    proof: Proof
    range_said: bool = False
    flags: list[Flag] = field(default_factory=list)
    photo: str | None = None
    condition_hint: str | None = None
    confirmed: bool = False


@dataclass
class Item:
    id: int
    version_id: int
    name_ta: str
    name_en: str
    variety: str | None
    qty: Decimal | None
    qty_unit: str | None
    photo: str | None
    sold_out: bool
    price_lines: list[PriceLine]
    proof: Proof


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int
    confidence: float | None
