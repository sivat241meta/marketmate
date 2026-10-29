"""Task 103: canonical local item name after a variety correction.

Task 97 turns ujala/krishnagiri drafts into brinjal, but when the model
already resolved name_en to brinjal the local name stayed as the spoken
variety ("உஜாலா", "வரி கிருஷ்ணகிரி வரி"). At draft creation a local
name that is just a variety alias (any script) or an alias plus filler
words now becomes the item's canonical local name; the Task 97 rename
path always sets it too (English fallback when the shop language has
no canonical name). Seller-chosen names, canonical names and synonyms
are untouched. No network: canned extract JSON only.
"""

from __future__ import annotations

from decimal import Decimal

from app.models import DraftItem, PriceLine, Proof, Transcript, Turn
from app.pipeline.extract import parse_extract_json
from app.pipeline.names import (
    correct_draft_from_variety,
    display_name_local,
    repair_variety_local_name,
)

CANNED_VARIETY_LOCALS = {"items": [
    {"name_spoken": "ujala", "name_en": "brinjal", "name_local": "உஜாலா",
     "variety": "ujala",
     "prices": [{"said": "kilo sixty", "price": 60,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [3], "quote": "ujala kilo sixty"},
    {"name_spoken": "வரி கிருஷ்ணகிரி வரி", "name_en": "brinjal",
     "name_local": "வரி கிருஷ்ணகிரி வரி", "variety": "krishnagiri",
     "prices": [{"said": "kilo seventy", "price": 70,
                "per_amount": 1, "unit": "kg"}],
     "range_said": False, "qty_said": None, "qty": None, "qty_unit": None,
     "turn_ids": [4], "quote": "வரி கிருஷ்ணகிரி வரி kilo seventy"},
]}


def _transcript() -> Transcript:
    texts = ["beans kilo forty", "ooty carrot kilo thirty",
             "ujala kilo sixty", "வரி கிருஷ்ணகிரி வரி kilo seventy"]
    turns = [Turn(id=i + 1, start_ms=i * 3000, end_ms=(i + 1) * 3000,
                  text=text) for i, text in enumerate(texts)]
    return Transcript(text=" ".join(texts), duration_ms=12000, turns=turns)


def _drafts(canned=None, language="ta"):
    items = parse_extract_json(canned or CANNED_VARIETY_LOCALS,
                               _transcript(), language=language)
    for item in items:
        correct_draft_from_variety(item, language=language)
    return items


def test_spoken_variety_becomes_canonical_item_name():
    items = _drafts()
    assert [i.name_en for i in items] == ["brinjal", "brinjal"]
    assert [i.name_local for i in items] == ["கத்திரிக்காய்", "கத்திரிக்காய்"]
    assert [i.variety for i in items] == ["ujala", "krishnagiri"]


def test_latin_alias_plus_filler_becomes_canonical():
    canned = {"items": [
        {"name_spoken": "வரி krishnagiri வரி", "name_en": "brinjal",
         "name_local": "வரி krishnagiri வரி", "variety": "krishnagiri",
         "prices": [{"said": "kilo seventy", "price": 70,
                    "per_amount": 1, "unit": "kg"}],
         "range_said": False, "qty_said": None, "qty": None,
         "qty_unit": None, "turn_ids": [4],
         "quote": "வரி krishnagiri வரி kilo seventy"},
        {"name_spoken": "ujala", "name_en": "brinjal",
         "name_local": "ujala", "variety": "ujala",
         "prices": [{"said": "kilo sixty", "price": 60,
                    "per_amount": 1, "unit": "kg"}],
         "range_said": False, "qty_said": None, "qty": None,
         "qty_unit": None, "turn_ids": [3], "quote": "ujala kilo sixty"},
    ]}
    items = _drafts(canned)
    assert [i.name_local for i in items] == ["கத்திரிக்காய்", "கத்திரிக்காய்"]
    assert [i.variety for i in items] == ["krishnagiri", "ujala"]


def test_hindi_shop_gets_hindi_canonical_name():
    items = _drafts(language="hi")
    assert [i.name_local for i in items] == ["बैंगन", "बैंगन"]
    assert [i.variety for i in items] == ["ujala", "krishnagiri"]


def test_task97_rename_sets_shop_language_name():
    from app.pipeline.names import decide_name_from_variety

    # Tamil: canonical Tamil name (as before).
    name_en, variety, local, word = decide_name_from_variety(
        "carrot", "ujala", "ujala", "ujala kilo sixty", language="ta")
    assert (name_en, variety, local) == ("brinjal", "ujala", "கத்திரிக்காய்")
    assert word == "ujala"
    # Hindi: Hindi canonical name.
    _, _, local, _ = decide_name_from_variety(
        "carrot", "ujala", "ujala", "ujala kilo sixty", language="hi")
    assert local == "बैंगन"
    # No canonical name for the shop language: English fallback.
    _, _, local, word = decide_name_from_variety(
        "carrot", "ujala", "ujala", "ujala kilo sixty", language="te")
    assert local == "brinjal"
    assert word == "ujala"


def _draft(name_en, name_local, variety=None):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety, match_key=name_en,
        price_lines=[PriceLine(Decimal(10), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=name_en, turn_ids=[1], start_ms=0, end_ms=1000),
    )


def test_seller_chosen_name_untouched(tmp_path):
    from app import db

    conn = db.connect(tmp_path)
    shop_id, _, _ = db.create_shop(
        conn, name="T103 Stall", phone="+914400000103", area="Koyambedu",
        language="ta", currency="INR", shop_type="vegetable")
    db.save_chosen_name(conn, shop_id, "brinjal", "ujala",
                        "செல்ல கத்திரி", "seller brinjal")
    items = _drafts()
    for item in items:
        # Same guard as the run/board paths: chosen names skip correction.
        if db.chosen_name_for(conn, shop_id, db.match_key_of(item),
                              item.variety) is None:
            correct_draft_from_variety(item, language="ta")
    db.save_drafts(conn, db.create_session(conn, shop_id, "video"), items)
    assert items[0].name_local == "செல்ல கத்திரி"
    assert items[0].name_en == "seller brinjal"
    assert items[1].name_local == "கத்திரிக்காய்"


def test_normal_item_names_untouched():
    assert repair_variety_local_name("beans", "பீன்ஸ்") == "பீன்ஸ்"
    assert repair_variety_local_name("carrot", "கேரட்") == "கேரட்"
    # A known synonym of the item is a real name, not a variety.
    assert repair_variety_local_name("brinjal", "eggplant") == "eggplant"
    assert repair_variety_local_name("okra", "bhindi") == "bhindi"
    # An alias for a different item is left for the Task 97 rename path.
    assert repair_variety_local_name("carrot", "உஜாலா") == "உஜாலா"
    # Filler alone, or no canonical name, means nothing to fix.
    assert repair_variety_local_name("brinjal", "வரி") == "வரி"
    assert repair_variety_local_name("brinjal", "உஜாலா", language="te") == "உஜாலா"
    assert repair_variety_local_name("other", "உஜாலா") == "உஜாலா"


def test_single_word_alias_becomes_canonical():
    assert repair_variety_local_name("brinjal", "உஜாலா") == "கத்திரிக்காய்"
    assert repair_variety_local_name("banana", "பூவன்") == "வாழைப்பழம்"
    assert repair_variety_local_name("brinjal", "உஜாலா", language="hi") == "बैंगन"


def test_variety_tag_shows_shop_language():
    assert display_name_local("கத்திரிக்காய்", "ujala") == "கத்திரிக்காய் (உஜாலா)"
    assert (display_name_local("கத்திரிக்காய்", "krishnagiri")
            == "கத்திரிக்காய் (கிருஷ்ணகிரி)")
    # Hindi has no local variety word, so the tag keeps English.
    assert (display_name_local("बैंगन", "ujala", language="hi")
            == "बैंगन (Ujala)")


def test_board_variety_local_becomes_canonical():
    from app.pipeline.board import parse_board_json

    items = parse_board_json(
        {"lines": [{"name_as_written": "ujala", "name_en": "brinjal",
                    "name_local": "உஜாலா", "price": 60, "read": "60",
                    "per_amount": 1, "unit": "kg"}]},
        "/tmp/board.jpg")
    assert items[0].name_local == "கத்திரிக்காய்"
    assert items[0].name_en == "brinjal"
