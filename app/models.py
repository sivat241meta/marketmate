from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

UNITS = ("kg", "g", "l", "ml", "piece", "dozen", "bunch", "packet")


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
    number_check: str | None = None
    source: str | None = None


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
    name_local: str
    name_en: str
    variety: str | None
    price_lines: list[PriceLine]
    qty: Decimal | None
    qty_unit: str | None
    proof: Proof
    range_said: bool = False
    flags: list[Flag] = field(default_factory=list)
    photo: str | None = None
    photo_candidates: list[str] = field(default_factory=list)
    condition_hint: str | None = None
    confirmed: bool = False
    match_key: str | None = None


@dataclass
class Item:
    id: int
    version_id: int
    name_local: str
    name_en: str
    variety: str | None
    qty: Decimal | None
    qty_unit: str | None
    photo: str | None
    sold_out: bool
    price_lines: list[PriceLine]
    proof: Proof
    stock_qty: Decimal | None = None
    stock_unit: str | None = None
    stock_source: str | None = None
    match_key: str | None = None


@dataclass
class Box:
    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int
    confidence: float | None


@dataclass
class Purchase:
    id: int
    shop_id: int
    date: str
    name_en: str
    name_local: str
    qty: Decimal | None
    unit: str | None
    total_cost: Decimal | None
    source: str


@dataclass
class PurchaseDraft:
    name_spoken: str
    name_local: str
    name_en: str
    qty: Decimal | None
    unit: str | None
    total_cost: Decimal | None
    proof: Proof
    flags: list[Flag] = field(default_factory=list)
    confirmed: bool = False
