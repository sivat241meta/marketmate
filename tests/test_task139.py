"""Task 139: item names come from the seller's spoken words, deterministically.

The same real 106 s Tamil stall video gave different names run to run
(Task 136's qualifier map was not enough): two identical potato titles
at two prices, a garbled "செவ்வாழ வாழை (Sevvazh)", "green fruit" for
கிர்ணி, and corn without its "sweet". After extraction, each item's
spoken span re-derives its names: the local name is the seller's own
words, the variety the English qualifier, the English name its base.
Same-title lines at different prices are flagged on both lines for a
rename, never merged. No model calls: fixture spans plus the canned
21-item model run only.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from test_task136 import stall_text, stall_transcript

from app import db
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.checks import flag_same_name_two_prices
from app.pipeline.names import english_title, local_title

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_tamil_stall_1_model.json"


def model_run() -> dict:
    payload = json.loads(FIXTURE.read_text())
    assert len(payload["items"]) == 21
    return payload


def parsed_items() -> list:
    from app.pipeline.extract import parse_extract_json

    return parse_extract_json(model_run(), stall_transcript(), language="ta")


def draft(name_en, name_local, price, variety=None, quote=""):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety, match_key=name_en,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg", "")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote or f"{name_en} {price}", turn_ids=[1],
                    start_ms=0, end_ms=1000),
        flags=[], confirmed=True)


def titles(item) -> tuple[str, str]:
    return (local_title(item.name_local, item.variety, item.name_en, "ta"),
            english_title(item.name_en, item.variety))


# --- 1. spoken name derivation ------------------------------------------------

def test_spoken_name_stops_at_quantity():
    from app.pipeline.spoken import spoken_item_name

    assert (spoken_item_name("புது உருளைக்கிழங்கு, கிலோ இருபத்தைந்து ரூபா")
            == "புது உருளைக்கிழங்கு")
    assert (spoken_item_name("Sweet corn கிலோ அஞ்சு பீஸ் இருபது")
            == "Sweet corn")
    assert (spoken_item_name("சின்ன வாழைப்பழம் ஒரு டஜன் நூறு ரூபா")
            == "சின்ன வாழைப்பழம்")
    assert (spoken_item_name("கோவக்காய் இருபது ரூபா ஒரு ஒரு கிலோ")
            == "கோவக்காய்")


def test_spoken_name_collapses_repeats_and_punctuation():
    from app.pipeline.spoken import spoken_item_name

    assert (spoken_item_name("உருளைக்கிழங்கு,உருளைக்கிழங்கு, கிலோ இருவது ரூபா")
            == "உருளைக்கிழங்கு")
    assert (spoken_item_name("கிறன் கிறன் ஃப்ரூட் ஒரு பீஸ் அம்பது ரூபா")
            == "கிறன் ஃப்ரூட்")


def test_spoken_name_bare_price_is_empty():
    from app.pipeline.spoken import spoken_item_name

    assert spoken_item_name("இருபத்தைந்து.") == ""
    assert spoken_item_name("அம்பது ரூபா.") == ""
    assert spoken_item_name("") == ""
    assert spoken_item_name(None) == ""


# --- 2. the 21-item run is fixed from the spans -------------------------------

def test_fixture_spans_come_from_the_transcript():
    text = stall_text()
    for raw in model_run()["items"]:
        assert raw["quote"] in text, raw["quote"]


def test_run_post_processing_gives_seller_word_titles():
    items = parsed_items()
    got = [(item.name_local, item.name_en, item.variety) for item in items]
    assert got[0] == ("உருளைக்கிழங்கு", "potato", None)
    assert got[1] == ("புது உருளைக்கிழங்கு", "potato", "new")
    assert got[2][0:2] == ("சின்ன வெங்காயம்", "small onion")
    assert got[2][2] is None  # "small" is already in the base name
    assert got[5] == ("Sweet corn", "corn", "sweet")
    assert got[11] == ("செவ்வாழை", "banana", "red")
    assert got[12] == ("பச்சை வாழைப்பழம்", "banana", "green")
    assert got[13][0:2] == ("கிறன் ஃப்ரூட்", "muskmelon")
    assert items[13].match_key == "muskmelon"
    assert got[14] == ("சின்ன வாழைப்பழம்", "banana", "small")


def test_run_final_titles_match_the_contract():
    items = parsed_items()
    assert titles(items[1]) == ("புது உருளைக்கிழங்கு", "new potato")
    assert titles(items[0]) == ("உருளைக்கிழங்கு", "potato")
    assert titles(items[11]) == ("செவ்வாழை", "red banana")
    assert titles(items[14]) == ("சின்ன வாழைப்பழம்", "small banana")
    assert titles(items[12]) == ("பச்சை வாழைப்பழம்", "green banana")
    assert titles(items[5]) == ("Sweet corn", "sweet corn")
    assert items[13].name_en == "muskmelon"
    assert "கிறன் கிறன் ஃப்ரூட்" in items[13].proof.quote


def test_no_duplicate_titles_remain():
    items = parsed_items()
    seen: dict[tuple[str, str], str] = {}
    for item in items:
        key = titles(item)
        price = str(item.price_lines[0].price)
        if key in seen:
            assert seen[key] == price, key
        seen[key] = price
    flag_same_name_two_prices(items, language="ta")
    assert [flag.code for item in items for flag in item.flags] == []


def test_prices_untouched_by_post_processing():
    from app.pipeline.spoken import apply_spoken_names

    items = parsed_items()
    expected = [str(raw["prices"][0]["price"])
                for raw in model_run()["items"]]
    assert [str(item.price_lines[0].price) for item in items] == expected
    before = [(str(line.price), str(line.per_amount), line.unit)
              for item in items for line in item.price_lines]
    assert apply_spoken_names(items, language="ta") == 0  # idempotent
    after = [(str(line.price), str(line.per_amount), line.unit)
             for item in items for line in item.price_lines]
    assert after == before


def test_missing_span_keeps_model_names():
    from app.pipeline.spoken import apply_spoken_name

    item = draft("banana", "செவ்வாழ வாழை", "100", variety="Sevvazh")
    item.name_spoken = ""
    item.proof.quote = ""
    assert apply_spoken_name(item, language="ta") is False
    assert (item.name_local, item.name_en, item.variety) == (
        "செவ்வாழ வாழை", "banana", "Sevvazh")


# --- 3. muskmelon glossary -----------------------------------------------------

def test_muskmelon_spoken_forms():
    from app.pipeline.names import find_name_in_text, resolve_name

    for spoken in ("கிர்ணி", "கிறணி", "கிறன்", "kirni", "kiran",
                   "கிறன் ஃப்ரூட்", "கிர்ணி பழம்", "கிறணி ஃப்ரூட்",
                   "கிறன் கிறன்", "கிறன் கிறன் ஃப்ரூட்",
                   "கிறன் கிறன் பழம்", "kirni fruit", "kiran fruit",
                   "kiran kiran fruit"):
        assert find_name_in_text(spoken) == "muskmelon", spoken
        assert resolve_name(spoken)[0] == "muskmelon", spoken


def test_qualifier_words_map_to_english():
    from app.pipeline.names import normalize_qualifier

    assert normalize_qualifier("புது") == "new"
    assert normalize_qualifier("puthu") == "new"
    assert normalize_qualifier("சின்ன") == "small"
    assert normalize_qualifier("sinna") == "small"
    assert normalize_qualifier("பெரிய") == "big"
    assert normalize_qualifier("நாட்டு") == "country"
    assert normalize_qualifier("பச்சை") == "green"
    assert normalize_qualifier("செவ்") == "red"
    assert normalize_qualifier("செவ்வாழை") == "red"
    assert normalize_qualifier("sweet") == "sweet"


# --- 4. duplicate titles are flagged on both lines, never merged ---------------

def test_same_title_two_prices_flags_both():
    first = draft("potato", "உருளைக்கிழங்கு", "20")
    second = draft("potato", "உருளைக்கிழங்கு", "25")
    flag_same_name_two_prices([first, second])
    for item in (first, second):
        assert [flag.code for flag in item.flags] == ["SAME_ITEM_TWO_PRICES"]
        assert item.flags[0].message == (
            "Two prices for potato — same item or different kinds?")
        assert item.flags[0].blocking is False
    assert len(first.price_lines) == len(second.price_lines) == 1


def test_same_display_title_flags_even_when_fields_differ():
    # Same red-banana title through different stored local names.
    first = draft("banana", "செவ்வாழை", "100", variety="red")
    second = draft("banana", "வாழைப்பழம்", "90", variety="red")
    assert titles(first) == titles(second)
    flag_same_name_two_prices([first, second])
    assert first.flags and second.flags


def test_different_titles_or_same_price_not_flagged():
    plain = draft("potato", "உருளைக்கிழங்கு", "20")
    new = draft("potato", "புது உருளைக்கிழங்கு", "25", variety="new")
    flag_same_name_two_prices([plain, new])
    assert plain.flags == [] and new.flags == []
    twin = draft("potato", "உருளைக்கிழங்கு", "20")
    flag_same_name_two_prices([plain, twin])
    assert plain.flags == [] and twin.flags == []
    unknown = draft("other", "சுரக்காய்", "40")
    unknown.name_en = "other"
    other = draft("other", "சுரக்காய்", "50")
    other.name_en = "other"
    flag_same_name_two_prices([unknown, other])
    assert unknown.flags == [] and other.flags == []


def test_review_shows_duplicate_note_and_rename_boxes(tmp_path):
    from test_task57 import create_shop, make_client, seed_review_session, token_of

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [
        draft("potato", "உருளைக்கிழங்கு", "20",
              quote="உருளைக்கிழங்கு கிலோ இருவது"),
        draft("potato", "உருளைக்கிழங்கு", "25",
              quote="உருளைக்கிழங்கு கிலோ இருபத்தைந்து"),
    ])

    conn = db.connect(tmp_path / "data")
    try:
        items = db.load_drafts(conn, session_id)
        flag_same_name_two_prices(items)
        db.save_drafts(conn, session_id, items)
    finally:
        conn.close()
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Two prices for potato — same item or different kinds?" in html
    assert html.count("data-rename-open") == 2
