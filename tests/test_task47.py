"""Task 47: real shop names (ujala brinjal, banana varieties) and answer keys.

No network: extraction uses canned Spark JSON fed to parse_extract_json;
benchmark clip-missing uses tmp dirs.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, Item, PriceLine, Proof, Transcript, Turn
from app.pipeline.extract import parse_extract_json


def _proof(quote="q"):
    return Proof(quote=quote, turn_ids=[1], start_ms=0, end_ms=1000)


def _item(name_en, variety, price, name_local=""):
    return Item(
        id=0, version_id=0, name_local=name_local or name_en, name_en=name_en,
        variety=variety, qty=None, qty_unit=None, photo=None, sold_out=False,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        proof=_proof(),
    )


def _transcript(text: str) -> Transcript:
    turn = Turn(id=1, start_ms=0, end_ms=3000, text=text)
    return Transcript(text=text, duration_ms=3000, turns=[turn])


# --- 1. names map correctly ---

def test_brinjal_ujala_nickname():
    from app.pipeline.names import resolve_name

    assert resolve_name("உஜாலா") == ("brinjal", "ujala")
    assert resolve_name("ujala") == ("brinjal", "ujala")
    assert resolve_name("ujjala") == ("brinjal", "ujala")
    # An explicitly said variety wins over the nickname default.
    assert resolve_name("ujjala", "Krishnagiri") == ("brinjal", "krishnagiri")
    assert resolve_name("உஜாலா", "krishnagiri") == ("brinjal", "krishnagiri")


def test_banana_varieties():
    from app.pipeline.names import resolve_name

    cases = [
        ("பூவன்", ("banana", "poovan")),
        ("poovan", ("banana", "poovan")),
        ("ஏலக்கி", ("banana", "yelakki")),
        ("ஏலகி", ("banana", "yelakki")),
        ("yelakki", ("banana", "yelakki")),
        ("elakki", ("banana", "yelakki")),
        ("கற்பூரவள்ளி", ("banana", "karpooravalli")),
        ("karpooravalli", ("banana", "karpooravalli")),
        ("தேன்வாழை", ("banana", "thenvazhai")),
        ("thenvazhai", ("banana", "thenvazhai")),
        ("செவ்வாழை", ("banana", "red")),
        ("sevvazhai", ("banana", "red")),
        ("red banana", ("banana", "red")),
        ("பச்சை வாழை", ("banana", "green")),
        ("pachai vazhai", ("banana", "green")),
        ("green banana", ("banana", "green")),
        ("நேந்திரன்", ("banana", "nendran")),
        ("nendran", ("banana", "nendran")),
        ("ரஸ்தாளி", ("banana", "rasthali")),
        ("rasthali", ("banana", "rasthali")),
    ]
    for spoken, expected in cases:
        assert resolve_name(spoken) == expected, spoken


def test_ooty_carrot_and_broad_beans():
    from app.pipeline.names import resolve_name

    assert resolve_name("ஊட்டி கேரட்") == ("carrot", "ooty")
    assert resolve_name("ooty carrot") == ("carrot", "ooty")
    assert resolve_name("அவரைக்காய்") == ("broad beans", None)
    assert resolve_name("avaraikkai") == ("broad beans", None)


# --- 2. extraction fixture from shop1 transcript ---

SHOP1_TRANSCRIPT = (
    "beans, ஒரு கிலோ நூற்றி இருபது, carrot ஊத்தி carrot ஊட்டி வந்து "
    "பார்த்தீங்கன்னா எண்பது ரூபா avaraikkai எண்பது ரூபா ujjala அறுபது "
    "அறுபது ரூபா vari Krishnagiri vari வந்து அறுபது ரூபா"
)


def test_shop1_brinjal_not_ujjala():
    canned = {"items": [{
        "name_spoken": "ujjala",
        "name_en": "ujjala",
        "variety": "Krishnagiri",
        "prices": [
            {"said": "அறுபது", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "அறுபது ரூபா", "price": 60,
             "per_amount": None, "unit": None},
            {"said": "அறுபது ரூபா", "price": 60,
             "per_amount": None, "unit": None},
        ],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": ("ujjala அறுபது அறுபது ரூபா vari Krishnagiri vari "
                  "வந்து அறுபது ரூபா"),
    }]}
    (item,) = parse_extract_json(canned, _transcript(SHOP1_TRANSCRIPT),
                                 language="ta")
    assert item.name_en == "brinjal"
    assert item.variety == "krishnagiri"
    assert len(item.price_lines) == 1
    assert item.price_lines[0].price == Decimal(60)


def test_shop1_ujala_default_when_no_variety_said():
    canned = {"items": [{
        "name_spoken": "ujjala",
        "name_en": "ujjala",
        "variety": None,
        "prices": [{"said": "அறுபது", "price": 60,
                    "per_amount": None, "unit": None}],
        "range_said": False,
        "qty_said": None,
        "qty": None,
        "qty_unit": None,
        "turn_ids": [1],
        "quote": "ujjala அறுபது",
    }]}
    (item,) = parse_extract_json(canned, _transcript("ujjala அறுபது"),
                                 language="ta")
    assert item.name_en == "brinjal"
    assert item.variety == "ujala"


# --- 3. variety billing ---

def _banana_shop():
    return [
        _item("banana", "poovan", 60, "வாழைப்பழம்"),
        _item("banana", "yelakki", 100, "வாழைப்பழம்"),
        _item("banana", "karpooravalli", 80, "வாழைப்பழம்"),
        _item("banana", "thenvazhai", 80, "வாழைப்பழம்"),
        _item("banana", "red", 100, "வாழைப்பழம்"),
        _item("banana", "green", 40, "வாழைப்பழம்"),
    ]


def test_poovan_picks_poovan_item(tmp_path):
    from app import db
    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    items = _banana_shop()
    lines, leftover = parse_order("பூவன் பழம் ஒரு கிலோ", items, "ta")
    assert len(lines) == 1
    assert lines[0].options in (None, [])
    assert (lines[0].qty, lines[0].unit) == (Decimal(1), "kg")
    from app.market.order_parse import item_like_leftovers

    assert item_like_leftovers(leftover, [w.name_en for w in lines]) == []
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000001", area="A", language="ta",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken="banana", name_local="வாழைப்பழம்",
                      name_en="banana", variety=item.variety,
                      price_lines=[PriceLine(Decimal(str(item.price_lines[0].price)),
                                             Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof())
            for item in items
        ])
        db.set_published(conn, version_id, True)
        quote = build_quote(conn, shop_id, lines)
    finally:
        conn.close()
    assert quote.lines[0].status == "priced"
    assert quote.lines[0].unit_price == Decimal(60)
    assert quote.lines[0].line_total == Decimal("60.00")


def test_bare_banana_asks_which_one(tmp_path):
    from app import db
    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    items = _banana_shop()
    lines, _ = parse_order("வாழைப்பழம் ஒரு கிலோ", items, "ta")
    assert len(lines) == 1
    options = lines[0].options or []
    assert len(options) >= 2
    joined = " ".join(options).lower()
    assert "poovan" in joined and "yelakki" in joined
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000001", area="A", language="ta",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken="banana", name_local="வாழைப்பழம்",
                      name_en="banana", variety=item.variety,
                      price_lines=[PriceLine(Decimal(str(item.price_lines[0].price)),
                                             Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof())
            for item in items
        ])
        db.set_published(conn, version_id, True)
        quote = build_quote(conn, shop_id, lines)
    finally:
        conn.close()
    assert quote.lines[0].status == "choose"
    assert quote.lines[0].line_total is None
    note = quote.lines[0].note or ""
    assert "poovan" in note.lower() and "yelakki" in note.lower()


# --- 4. benchmark keys ---

def test_answer_keys_load():
    for name, count in (("shop1.json", 4), ("shop2.json", 6)):
        key = json.loads(
            (Path("eval/answers") / name).read_text(encoding="utf-8"))
        assert " " in key["clip"], name  # path with spaces must survive
        assert len(key["items"]) == count, name
    shop2 = json.loads(
        (Path("eval/answers/shop2.json")).read_text(encoding="utf-8"))
    assert shop2["confirmed"] is False


def test_benchmark_skips_missing_clip(tmp_path, monkeypatch, capsys):
    import shutil

    from scripts import benchmark

    answers = tmp_path / "answers"
    out = tmp_path / "out"
    answers.mkdir()
    out.mkdir()
    for name in ("shop1.json", "shop2.json"):
        shutil.copy(Path("eval/answers") / name, answers / name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["benchmark.py", "--answers-dir", str(answers),
         "--out-dir", str(out)])
    benchmark.main()
    captured = capsys.readouterr()
    assert "shop1.json" in captured.out and "shop2.json" in captured.out
    assert "clip" in captured.out.lower()
    assert "missing" in captured.out.lower() or "not found" in captured.out.lower()
