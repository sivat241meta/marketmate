"""Task 136: keep the seller's variety words in every title.

A real Tamil stall video names two kinds of potato and three kinds of
banana; the titles must keep the seller's own distinguishing words
("new potato", "red banana") in both scripts, everywhere a title is
built. No model calls: fixture spans plus canned extract JSON only.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models import DraftItem, PriceLine, Proof, Transcript, Turn

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_tamil_stall_1.txt"
IST = ZoneInfo("Asia/Kolkata")


def stall_text() -> str:
    return FIXTURE.read_text().strip()


def stall_transcript() -> Transcript:
    text = stall_text()
    return Transcript(text=text, duration_ms=106000,
                      turns=[Turn(id=1, start_ms=0, end_ms=106000,
                                  text=text)])


def draft(name_en, name_local, price, variety=None, quote=""):
    return DraftItem(
        name_spoken=name_en, name_local=name_local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg", "")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote or f"{name_en} {price}", turn_ids=[1],
                    start_ms=0, end_ms=1000),
        flags=[], confirmed=True)


# --- 1. qualifier map: transliterations become English -----------------------

def test_qualifier_map_tamil_transliterations():
    from app.pipeline.names import normalize_qualifier

    assert normalize_qualifier("puthu") == "new"
    assert normalize_qualifier("pudhu") == "new"
    assert normalize_qualifier("sinna") == "small"
    assert normalize_qualifier("chinna") == "small"
    assert normalize_qualifier("periya") == "big"
    assert normalize_qualifier("pachai") == "green"
    assert normalize_qualifier("nattu") == "country"
    assert normalize_qualifier("naati") == "country"


def test_qualifier_map_tamil_script_and_hindi():
    from app.pipeline.names import normalize_qualifier

    assert normalize_qualifier("புது") == "new"
    assert normalize_qualifier("சின்ன") == "small"
    assert normalize_qualifier("பெரிய") == "big"
    assert normalize_qualifier("பச்சை") == "green"
    assert normalize_qualifier("நாட்டு") == "country"
    assert normalize_qualifier("naya") == "new"
    assert normalize_qualifier("chhota") == "small"
    assert normalize_qualifier("bada") == "big"
    assert normalize_qualifier("hara") == "green"
    assert normalize_qualifier("lal") == "red"
    assert normalize_qualifier("desi") == "country"
    assert normalize_qualifier("meetha") == "sweet"


def test_qualifier_map_english_passes_through():
    from app.pipeline.names import normalize_qualifier, resolve_name

    assert normalize_qualifier("red") == "red"
    assert normalize_qualifier("green") == "green"
    assert normalize_qualifier("sweet") == "sweet"
    # The model's own English for anything else is kept as-is.
    assert resolve_name("tomato", "bengaluru") == ("tomato", "bengaluru")
    assert resolve_name("potato", "puthu") == ("potato", "new")
    assert resolve_name("banana", "sinna") == ("banana", "small")
    assert normalize_qualifier("bengaluru") is None
    assert normalize_qualifier(None) is None
    assert normalize_qualifier("  ") is None


# --- 2. titles differ in both scripts ----------------------------------------

def test_two_potato_titles_differ_in_both_scripts():
    from app.pipeline.names import english_title, local_title

    plain_en = english_title("potato", None)
    new_en = english_title("potato", "new")
    assert (plain_en, new_en) == ("potato", "new potato")
    plain_local = local_title("உருளைக்கிழங்கு", None, "potato")
    new_local = local_title("உருளைக்கிழங்கு", "new", "potato")
    assert (plain_local, new_local) == ("உருளைக்கிழங்கு",
                                       "புது உருளைக்கிழங்கு")


def test_banana_and_corn_english_titles():
    from app.pipeline.names import english_title, local_title

    assert english_title("banana", "red") == "red banana"
    assert english_title("banana", "small") == "small banana"
    assert english_title("banana", "green") == "green banana"
    assert english_title("corn", "sweet") == "sweet corn"
    assert local_title("வாழைப்பழம்", "red", "banana") == "செவ்வாழை"
    assert (local_title("வாழைப்பழம்", "small", "banana")
            == "சின்ன வாழைப்பழம்")
    assert (local_title("வாழைப்பழம்", "green", "banana")
            == "பச்சை வாழைப்பழம்")


def test_cultivar_varieties_keep_parenthetical_english():
    from app.pipeline.names import english_title

    assert english_title("banana", "poovan") == "Banana (Poovan)"
    assert english_title("other", "new") == ""


# --- 3. kirni glossary + video market words ----------------------------------

def test_kirni_resolves_to_muskmelon():
    from app.pipeline.names import resolve_name

    for spoken in ("கிர்ணி", "கிறணி", "கிறன்", "கிர்ணி பழம்",
                   "kirni", "kiran kiran fruit"):
        assert resolve_name(spoken)[0] == "muskmelon", spoken


def test_video_market_words_covered():
    from app.pipeline.names import resolve_name

    expected = {
        "சேப்பங்கிழங்கு": "colocasia",
        "கோவக்காய்": "ivy gourd",
        "சுரைக்காய்": "bottle gourd",
        "பூசணிக்காய்": "ash gourd",
        "வாழைக்காய்": "raw banana",
        "முள்ளங்கி": "radish",
        "பாகற்காய்": "bitter gourd",
        "மாங்கா": "raw mango",
        "எலுமிச்சை": "lemon",
        "நெல்லிக்காய்": "gooseberry",
        "பூண்டு": "garlic",
    }
    for word, name_en in expected.items():
        assert resolve_name(word)[0] == name_en, word


def test_fixture_spans_resolve():
    from app.pipeline.names import find_name_in_text

    text = stall_text()
    for span, name_en in (
            ("புது உருளைக்கிழங்கு", "potato"),
            ("சின்ன வெங்காயம்", "small onion"),
            ("சுரைக்காய்", "bottle gourd"),
            ("சேப்பங்கிழங்கு", "colocasia"),
            ("தேங்கா", "coconut"),
            ("பூசணிக்காய்", "ash gourd"),
            ("கிறன் கிறன் ஃப்ரூட்", "muskmelon"),
            ("வாழைக்காய்", "raw banana"),
            ("முள்ளங்கி", "radish"),
            ("கோவக்காய்", "ivy gourd"),
            ("பாகற்காய்", "bitter gourd"),
            ("மாங்கா", "raw mango"),
            ("எலுமிச்சை பழம்", "lemon"),
            ("Sweet corn", "corn"),
            ("வெள்ளரிக்கா", "cucumber")):
        assert span in text, span
        assert find_name_in_text(span) == name_en, span


# --- 4. extract keeps the spoken qualifier -----------------------------------

def _canned(name_spoken, name_en, name_local, variety, price, quote):
    return {
        "name_spoken": name_spoken, "name_en": name_en,
        "name_local": name_local, "variety": variety,
        "prices": [{"said": "said", "price": price, "per_amount": 1,
                    "unit": "kg"}],
        "range_said": False, "qty_said": None, "qty": None,
        "qty_unit": None, "turn_ids": [1], "quote": quote,
    }


def test_extract_restores_spoken_qualifiers():
    from app.pipeline.extract import parse_extract_json

    data = {"items": [
        _canned("உருளைக்கிழங்கு", "potato", "உருளைக்கிழங்கு",
                None, 20, "உருளைக்கிழங்கு கிலோ இருவது ரூபா"),
        _canned("புது உருளைக்கிழங்கு", "potato", "உருளைக்கிழங்கு",
                "puthu", 25,
                "புது உருளைக்கிழங்கு கிலோ இருபத்தைந்து ரூபா"),
        _canned("செவ்வாழை", "banana", "வாழைப்பழம்",
                "red", 100, "செவ்வாழை அஞ்சு பீஸ் நூறு ரூபா"),
        _canned("சின்ன வாழைப்பழம்", "banana", "வாழைப்பழம்",
                "sinna", 100,
                "சின்ன வாழைப்பழம் ஒரு டஜன் நூறு ரூபா"),
        _canned("பச்சை வாழைப்பழம்", "banana", "வாழைப்பழம்",
                "green", 20,
                "பச்சை வாழைப்பழம் மூணு பீஸ் இருபது ரூபா"),
        _canned("Sweet corn", "corn", "சோளம்",
                "sweet", 20, "Sweet corn கிலோ அஞ்சு பீஸ் இருபது"),
        _canned("கிறன் கிறன் ஃப்ரூட்", "kiran kiran fruit", None,
                None, 50,
                "கிறன் கிறன் ஃப்ரூட் ஒரு பீஸ் அம்பது ரூபா"),
    ]}
    items = parse_extract_json(data, stall_transcript(), language="ta")
    got = [(item.name_en, item.variety, item.name_local) for item in items]
    assert got[0] == ("potato", None, "உருளைக்கிழங்கு")
    assert got[1] == ("potato", "new", "புது உருளைக்கிழங்கு")
    assert got[2] == ("banana", "red", "செவ்வாழை")
    assert got[3] == ("banana", "small", "சின்ன வாழைப்பழம்")
    assert got[4] == ("banana", "green", "பச்சை வாழைப்பழம்")
    assert got[5][0:2] == ("corn", "sweet")
    # Task 139: the local name is the seller's own words, so the spoken
    # "Sweet corn" wins over the canonical "சோளம்".
    assert got[5][2] == "Sweet corn"
    assert got[6][0] == "muskmelon"


def test_extract_never_invents_unspoken_qualifier():
    from app.pipeline.extract import parse_extract_json

    data = {"items": [_canned("உருளைக்கிழங்கு", "potato",
                              "உருளைக்கிழங்கு", None, 20,
                              "உருளைக்கிழங்கு கிலோ இருவது ரூபா")]}
    (item,) = parse_extract_json(data, stall_transcript(), language="ta")
    assert item.name_local == "உருளைக்கிழங்கு"
    assert item.variety is None


def test_qualifier_variety_does_not_rename_item():
    from app.pipeline.names import correct_draft_from_variety

    item = draft("potato", "புது உருளைக்கிழங்கு", "25", variety="new",
                 quote="புது உருளைக்கிழங்கு கிலோ இருபத்தைந்து")
    assert correct_draft_from_variety(item, language="ta") is None
    assert (item.name_en, item.variety) == ("potato", "new")


def test_rename_validates_qualifier_to_english():
    from app.pipeline.namecheck import validate_names

    _, _, variety = validate_names(
        "உருளைக்கிழங்கு", "potato", "puthu", "ta")
    assert variety == "new"
    _, _, variety = validate_names(
        "வாழைப்பழம்", "banana", "Bengaluru", "ta")
    assert variety == "Bengaluru"


# --- 5. same name + same variety + different prices is flagged ---------------

def test_same_name_two_prices_flagged():
    from app.pipeline.checks import flag_same_name_two_prices

    first = draft("potato", "உருளைக்கிழங்கு", "20")
    second = draft("potato", "உருளைக்கிழங்கு", "25")
    flag_same_name_two_prices([first, second])
    # Task 139: both lines are flagged, never merged.
    for item in (first, second):
        assert [flag.code for flag in item.flags] == ["SAME_ITEM_TWO_PRICES"]
        assert item.flags[0].message == (
            "Two prices for potato — same item or different kinds?")
        assert item.flags[0].blocking is False


def test_different_varieties_or_same_price_not_flagged():
    from app.pipeline.checks import flag_same_name_two_prices

    plain = draft("potato", "உருளைக்கிழங்கு", "20")
    new = draft("potato", "புது உருளைக்கிழங்கு", "25", variety="new")
    flag_same_name_two_prices([plain, new])
    assert plain.flags == [] and new.flags == []
    twin = draft("potato", "உருளைக்கிழங்கு", "20")
    flag_same_name_two_prices([plain, twin])
    assert plain.flags == [] and twin.flags == []


# --- 6. review page + shop row render the variety in the title ---------------

def test_review_headers_show_variety_titles(tmp_path):
    from test_task57 import create_shop, make_client, seed_review_session, token_of

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [
        draft("potato", "உருளைக்கிழங்கு", "20"),
        draft("potato", "புது உருளைக்கிழங்கு", "25", variety="new"),
    ])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "புது உருளைக்கிழங்கு</span> · new potato" in html
    assert "உருளைக்கிழங்கு</span> · potato" in html


def test_shop_row_shows_variety_titles(tmp_path):
    from test_task57 import create_shop, make_client, seed_published, slug_of, token_of

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [
        draft("potato", "உருளைக்கிழங்கு", "20"),
        draft("potato", "புது உருளைக்கிழங்கு", "25", variety="new"),
    ])
    html = client.get(f"/s/{slug_of(tmp_path, token)}").text
    assert "புது உருளைக்கிழங்கு" in html
    assert "New potato" in html
    assert 'data-title-en="new potato"' in html


# --- 7. board, tags, CSV, Excel, WhatsApp include the variety ----------------

def _item(name_en, name_local, price, variety=None):
    from test_outputs import item as mk_item
    from test_outputs import pl

    return mk_item(name_en=name_en, name_local=name_local,
                   variety=variety, lines=[pl(price, 1, "kg")])


def test_board_pdf_includes_variety_titles():
    from test_outputs import demo_shop_row, pypdf_text

    from app.outputs.pdf import price_board_pdf

    shop = dict(demo_shop_row(), language="ta")
    pdf = price_board_pdf(
        shop,
        [_item("potato", "உருளைக்கிழங்கு", 20),
         _item("potato", "புது உருளைக்கிழங்கு", 25, variety="new")],
        datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/demo-stall")
    text = pypdf_text(pdf)
    assert "புது உருளைக்கிழங்கு" in text
    assert "new potato" in text


def test_tags_pdf_includes_variety_titles():
    from test_outputs import demo_shop_row, pypdf_text

    from app.outputs.pdf import price_tags_pdf

    shop = dict(demo_shop_row(), language="ta")
    pdf = price_tags_pdf(
        shop, [_item("banana", "வாழைப்பழம்", 100, variety="red")],
        datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/demo-stall")
    text = pypdf_text(pdf)
    assert "செவ்வாழை" in text
    assert "red banana" in text


def test_generic_csv_keeps_variety_column():
    from datetime import datetime as _dt

    from app.outputs.csv_export import generic_csv

    payload = generic_csv(
        [_item("potato", "புது உருளைக்கிழங்கு", 25, variety="new")],
        _dt(2026, 10, 28, 9, 0, tzinfo=IST))
    rows = list(csv.DictReader(io.StringIO(payload)))
    assert rows[0]["variety"] == "new"
    assert rows[0]["name_en"] == "potato"
    assert rows[0]["name_local"] == "புது உருளைக்கிழங்கு"


def test_pricelist_csv_and_excel_use_english_title(tmp_path):
    import openpyxl
    from test_task57 import create_shop, make_client, seed_bill, seed_published, token_of

    from app import db
    from app.outputs.excel import sales_workbook
    from app.outputs.pos_csv import pricelist_csv

    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    seed_published(tmp_path, token, [
        draft("potato", "புது உருளைக்கிழங்கு", "25", variety="new")])
    seed_bill(tmp_path, token,
              [("potato", "புது உருளைக்கிழங்கு", "new", "1", "kg",
                "25", "25.00")],
              "25.00", day="2026-10-27")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        rows = list(csv.DictReader(io.StringIO(
            pricelist_csv(conn, shop).decode("utf-8-sig"))))
        data = sales_workbook(conn, shop, "2026-10-27", "2026-10-27")
    finally:
        conn.close()
    assert rows[0]["item_name"] == "new potato"
    assert rows[0]["item_name_local"] == "புது உருளைக்கிழங்கு"
    book = openpyxl.load_workbook(io.BytesIO(data))
    line_names = [row[2].value
                  for row in book["Lines"].iter_rows(min_row=2)]
    assert "new potato" in line_names


def test_whatsapp_text_uses_variety_titles(tmp_path):
    from test_task54 import make_draft, seed_version
    from test_task57 import create_shop, make_client, token_of

    from app import db
    from app.web.seller import build_price_message

    token = token_of(create_shop(make_client(tmp_path)))
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        seed_version(conn, shop["id"], [
            make_draft(name_en="potato", name_local="புது உருளைக்கிழங்கு",
                       price="25", variety="new")], published=True)
        text = build_price_message(conn, shop, "en",
                                   base_url="http://x.test")
    finally:
        conn.close()
    assert "புது உருளைக்கிழங்கு (new potato)" in text
