"""Task 156: one sentence with many items is split into per-item proof spans.

A real 64 s Tamil stall video (shop owner 2, 17 items) opens with one
~30 s turn naming nine items. The draft items all carried the whole
turn as proof.quote, so every banana variety leaked into every item,
two items were titled "So sev vazhai இன்னைக்கு rate", and an ash
gourd line passed as banana with a green tick. After extraction each item
now keeps only its own words (own price phrase back to the previous
item's price end), names and single varieties come from that span
only, a claimed name missing from its span raises blocking
NAME_NOT_NEAR_PRICE, and the Mannur beans line folds into beans.
No model calls: the canned 17-item model run only.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.names import english_title, local_title

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_tamil_stall_owner2.json"

EXPECTED_SPANS = [
    "sev vazhai இன்னைக்கு rate rate 110 ரூபாய் கிலோ",
    "Nendran 100 ரூபாய்",
    "Karpuravalli 80",
    "பச்சை பழம் 50 ரூபாய் kilo",
    "Tharpoosani kilo 30",
    "Elaki kilo 120",
    "poosani ஒரு kilo 30 ரூபாய்",
    "kathirikkai kaal kilo 20 ரூபாய்",
    "avaraikkai kaal kilo 35",
]


def payload() -> dict:
    data = json.loads(FIXTURE.read_text())
    assert len(data["items"]) == 17
    assert len(data["turns"]) == 9
    return data


def owner2_transcript() -> Transcript:
    data = payload()
    return Transcript(
        text="", duration_ms=data["duration_ms"],
        turns=[Turn(**raw) for raw in data["turns"]])


def parsed_items() -> list:
    from app.pipeline.extract import parse_extract_json

    return parse_extract_json(payload(), owner2_transcript(), language="ta")


def lines(item) -> list[tuple[str, str, str]]:
    return [(str(line.price), str(line.per_amount), line.unit)
            for line in item.price_lines]


# --- 1. the fixture is the model's whole-turn output ---------------------------

def test_fixture_items_carry_whole_turn_quotes():
    data = payload()
    first = data["turns"][0]["text"]
    assert data["turns"][0]["end_ms"] - data["turns"][0]["start_ms"] == 30000
    for raw in data["items"][:9]:
        assert raw["turn_ids"] == [1]
        assert raw["quote"] == first


# --- 2. per-item spans ----------------------------------------------------------

def test_first_turn_splits_into_per_item_spans():
    items = parsed_items()
    assert [item.proof.quote for item in items[:9]] == EXPECTED_SPANS
    for item in items[:9]:
        assert item.proof.quote in owner2_transcript().turns[0].text


def test_span_clip_times_stay_inside_the_turn():
    items = parsed_items()
    turn = owner2_transcript().turns[0]
    for item in items[:9]:
        start, end = item.proof.start_ms, item.proof.end_ms
        assert turn.start_ms <= start <= end <= turn.end_ms
    starts = [item.proof.start_ms for item in items[:9]]
    assert starts == sorted(starts)
    assert items[0].proof.start_ms <= 500  # stripped "So, " shifts the clip
    assert items[8].proof.end_ms == turn.end_ms  # trailing words kept


# --- 3. single varieties and right names ----------------------------------------

def test_varieties_are_single_values_from_own_span():
    items = parsed_items()
    assert [item.variety for item in items[:9]] == [
        "red", "nendran", "karpooravalli", "green", None, "yelakki",
        None, None, None]
    for item in items:
        assert "/" not in (item.variety or "")


def test_items_3_5_get_the_right_names():
    items = parsed_items()
    third = items[3]
    assert (third.name_local, third.name_en, third.variety) == (
        "பச்சை பழம்", "banana", "green")
    assert local_title(third.name_local, third.variety, third.name_en,
                       "ta") == "பச்சை பழம்"
    assert english_title(third.name_en, third.variety) == "green banana"
    assert lines(third) == [("50", "1", "kg")]
    fifth = items[5]
    assert (fifth.name_en, fifth.variety) == ("banana", "yelakki")
    assert "ஏலக்கி" in local_title(fifth.name_local, fifth.variety,
                                 fifth.name_en, "ta")
    assert english_title(fifth.name_en, fifth.variety) == "Banana (Yelakki)"
    assert lines(fifth) == [("120", "1", "kg")]


def test_banana_variety_words_map():
    from app.pipeline.names import resolve_name

    assert resolve_name("sev vazhai") == ("banana", "red")
    assert resolve_name("nendran") == ("banana", "nendran")
    assert resolve_name("karpuravalli") == ("banana", "karpooravalli")
    assert resolve_name("பச்சை பழம்") == ("banana", "green")
    assert resolve_name("pachai pazham") == ("banana", "green")
    assert resolve_name("elaki") == ("banana", "yelakki")


# --- 4. a wrong item name never passes ------------------------------------------

def test_wrong_item_name_is_flagged_never_renamed():
    items = parsed_items()
    heard = items[6]
    assert (heard.name_local, heard.name_en, heard.variety) == (
        "வாழைப்பழம்", "banana", None)
    assert lines(heard) == [("30", "1", "kg")]
    flags = check_item(heard, {}, language="ta")
    flag = next(f for f in flags if f.code == "NAME_NOT_NEAR_PRICE")
    assert flag.blocking is True
    assert flag.message == (
        "Is this Banana? Just before ₹30 we heard 'poosani' (ash gourd).")
    assert flag.options == ["ash gourd", "banana"]
    assert heard.name_en == "banana"  # flagged, never silently renamed


def test_flagged_card_shows_needs_you_never_a_tick(tmp_path):
    from test_task57 import create_shop, make_client, seed_review_session, token_of

    items = parsed_items()
    heard = items[6]
    heard.flags = check_item(heard, {}, language="ta")
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [heard])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Needs you" in html
    assert 'data-needs="1"' in html
    assert 'data-needs="0"' not in html
    assert 'class="tick"' not in html
    assert "poosani" in html
    assert 'data-value="ash gourd"' in html


# --- 5. Mannur beans ------------------------------------------------------------

def test_mannur_line_folds_into_beans():
    items = parsed_items()
    assert len(items) == 16
    assert all("மன்னூர்" not in (item.name_local or "") for item in items)
    beans = items[10]
    assert (beans.name_en, beans.variety) == ("beans", "mannur")
    assert lines(beans) == [("35", "0.25", "kg"), ("70", "1", "kg")]
    assert "மன்னூர்ல" in beans.proof.quote
    codes = [flag.code for flag in check_item(beans, {}, language="ta")]
    assert "MULTI_PRICE_UNCLEAR" not in codes
    assert "NOT_HEARD" not in codes


def test_tens_oru_kilo_is_price_plus_one_kilo():
    from app.pipeline.numbers import find_numbers

    assert find_numbers("எழுபது ஒரு கிலோ") == [(70, "tamil"), (1, "tamil")]
    assert find_numbers("muppathu oru kilo") == [(30, "tamil"), (1, "tamil")]
    assert find_numbers("muppathu onnu") == [(31, "tamil")]


# --- 6. prices untouched ---------------------------------------------------------

def test_prices_untouched_by_splitting():
    items = parsed_items()
    raw = payload()["items"]

    def expected(index: int) -> list[tuple[str, str, str]]:
        return [(str(line["price"]), str(line["per_amount"]), line["unit"])
                for line in raw[index]["prices"]]

    for index in range(10):
        assert lines(items[index]) == expected(index), index
    assert lines(items[10]) == expected(10) + expected(11)
    for parsed, index in ((11, 12), (12, 13), (13, 14), (14, 15), (15, 16)):
        assert lines(items[parsed]) == expected(index), parsed
    assert all(item.qty is None for item in items)


# --- 7. Tamil gourd glossary -----------------------------------------------------

def test_tamil_gourd_glossary():
    from app.pipeline.names import find_name_in_text, resolve_name

    assert resolve_name("poosani") == ("ash gourd", None)
    assert find_name_in_text("பூசணி") == "ash gourd"
    assert find_name_in_text("தர்பூசணி") == "watermelon"
    assert resolve_name("tharpoosani") == ("watermelon", None)
    assert resolve_name("avaraikkai") == ("broad beans", None)
    assert resolve_name("kathirikkai") == ("brinjal", None)
    assert find_name_in_text("குடமிளகாய்") == "capsicum"
    assert find_name_in_text("பொடலங்காய்") == "snake gourd"
