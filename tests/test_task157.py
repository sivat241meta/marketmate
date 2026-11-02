"""Task 157: live-run fixes for owner 2's Tamil stall video.

The 64 s video ran once on the live site with Task 156's code: 17
prices were said but only 16 items came back, watermelon caught a
wrong NAME_NOT_NEAR_PRICE flag, and the red banana lost its variety.
The fixture rebuilds the 8 live turns exactly plus the model's items
as returned (whole-turn quotes, model names). Two variants: (A) the
model also returned the "மன்னூர்" line, which must fold into beans
as a second price line; (B) the model skipped it, so the coverage
check must add a MISSED_PRICE item that needs the seller. Tamil
spelling variants compare on a normalized form, glossary aliases
match whole words only, merged repeats ("vazhaiwazhai") collapse
before matching, and plain பூசணி is ash gourd. No model calls.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.models import Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.names import english_title, local_title

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_tamil_stall_owner2_live.json"

TURN_3_TEXT = "மன்னூர்ல இன்னைக்கு ரேட்டு எழுபது ஒரு கிலோ."

EXPECTED_QUOTES = [
    "sev vazhaiwazhai இன்னைக்கு rate நூற்றி பத்து ரூபா கிலோ",
    "நேந்திரன் நூறு ரூபா",
    "கற்பூரவள்ளி எண்பது",
    "பச்சை பழம் அம்பது ரூபா கிலோ",
    "தற்பூசணி கிலோ முப்பது",
    "ஏலகி கிலோ நூற்றி இருபது",
    "பூசணி ஒரு கிலோ முப்பது ரூபா",
    "கத்தரிக்கா கால் கிலோ இருபது ரூபா",
    "அவரக்கா கால் கிலோ முப்பத்தஞ்சு",
    "கேரட் கால் கிலோ இருபது ரூபா",
    "beans கால் கிலோ முப்பத்தஞ்சு",
    "சுரக்கா ஒரு கிலோ அறுபது ரூபா",
    "பொடலங்கா ஒரு கிலோ கிலோ எழுபது ரூபா",
    "வெண்டைக்கா ஒரு கிலோ அறுபது",
    "குடமுளகா ஒரு கிலோ நூறு",
    "வெள்ளரிக்கா ஒரு கிலோ அறுபது",
]

EXPECTED_LINES = [
    ("110", "1", "kg"), ("100", None, None), ("80", None, None),
    ("50", "1", "kg"), ("30", "1", "kg"), ("120", "1", "kg"),
    ("30", "1", "kg"), ("20", "0.25", "kg"), ("35", "0.25", "kg"),
    ("20", "0.25", "kg"), ("35", "0.25", "kg"), ("60", "1", "kg"),
    ("70", "1", "kg"), ("60", "1", "kg"), ("100", "1", "kg"),
    ("60", "1", "kg"),
]


def payload() -> dict:
    data = json.loads(FIXTURE.read_text())
    assert len(data["turns"]) == 8
    assert len(data["items"]) == 16
    assert "mannur_item" in data
    return data


def live_transcript() -> Transcript:
    data = payload()
    return Transcript(
        text="", duration_ms=data["duration_ms"],
        turns=[Turn(**raw) for raw in data["turns"]])


def items_a() -> list:
    """Variant A: the model also returned the மன்னூர் line."""
    from app.pipeline.extract import parse_extract_json

    data = payload()
    model = {"items": data["items"][:11] + [data["mannur_item"]]
             + data["items"][11:]}
    assert len(model["items"]) == 17
    return parse_extract_json(model, live_transcript(), language="ta")


def items_b() -> list:
    """Variant B: the model skipped it; the coverage check adds it back."""
    from app.pipeline.coverage import add_missed_price_items
    from app.pipeline.extract import parse_extract_json

    data = payload()
    parsed = parse_extract_json({"items": data["items"]},
                                live_transcript(), language="ta")
    return add_missed_price_items(parsed, live_transcript(), language="ta")


def lines(item) -> list[tuple]:
    return [(line.price, line.per_amount, line.unit)
            for line in item.price_lines]


def expected(index: int) -> list[tuple]:
    price, per, unit = EXPECTED_LINES[index]
    return [(Decimal(price),
             Decimal(per) if per is not None else None, unit)]


# --- 1. the fixture is the live run -------------------------------------------

def test_fixture_has_the_eight_live_turns_exactly():
    data = payload()
    assert data["duration_ms"] == 64480
    assert [(t["id"], t["start_ms"], t["end_ms"]) for t in data["turns"]] == [
        (1, 380, 12620), (2, 14220, 36460), (3, 39020, 41340),
        (4, 43180, 44860), (5, 46780, 48380), (6, 51020, 52780),
        (7, 54540, 56300), (8, 58460, 60220)]
    assert data["turns"][0]["text"].startswith("so, sev vazhaiwazhai")
    assert data["turns"][2]["text"] == TURN_3_TEXT
    assert "பொடலங்கா" in data["turns"][4]["text"]
    assert data["mannur_item"]["prices"] == [
        {"said": "எழுபது ஒரு கிலோ", "price": 70,
         "per_amount": 1, "unit": "kg"}]


def test_model_quotes_are_whole_turns():
    data = payload()
    first, second = data["turns"][0]["text"], data["turns"][1]["text"]
    for raw in data["items"][:4]:
        assert raw["turn_ids"] == [1]
        assert raw["quote"] == first
    for raw in data["items"][4:11]:
        assert raw["turn_ids"] == [2]
        assert raw["quote"] == second


def test_split_quotes_are_each_items_own_live_words():
    from app.pipeline.extract import parse_extract_json

    parsed = parse_extract_json({"items": payload()["items"]},
                                live_transcript(), language="ta")
    assert [item.proof.quote for item in parsed] == EXPECTED_QUOTES


# --- 2. watermelon: no false alarm --------------------------------------------

def test_watermelon_has_no_name_flag():
    melon = items_b()[4]
    assert (melon.name_local, melon.name_en) == ("தர்பூசணி", "watermelon")
    assert lines(melon) == expected(4)
    codes = [flag.code for flag in check_item(melon, {}, language="ta")]
    assert "NAME_NOT_NEAR_PRICE" not in codes


def test_poosani_inside_tharpoosani_does_not_count():
    from app.pipeline.names import find_items_in_text, item_name_in_text

    assert find_items_in_text("தர்பூசணி கிலோ முப்பது") == [
        ("தர்பூசணி", "watermelon")]
    assert find_items_in_text("தற்பூசணி கிலோ முப்பது") == []
    assert find_items_in_text("Tharpoosani kilo 30") == [
        ("Tharpoosani", "watermelon")]
    assert item_name_in_text("watermelon", "தற்பூசணி கிலோ முப்பது",
                             name_local="தர்பூசணி") is True


def test_task156_banana_still_flagged():
    from test_task156 import parsed_items

    heard = parsed_items()[6]
    flags = check_item(heard, {}, language="ta")
    flag = next(f for f in flags if f.code == "NAME_NOT_NEAR_PRICE")
    assert flag.blocking is True
    assert flag.message == (
        "Is this Banana? Just before ₹30 we heard 'poosani' (ash gourd).")
    assert flag.options == ["ash gourd", "banana"]


def test_spelling_variant_normalizer():
    from app.pipeline.names import normalize_tamil_spelling as norm

    pairs = [
        ("தற்பூசணி", "தர்பூசணி"),
        ("கத்தரிக்கா", "கத்தரிக்காய்"),
        ("வெண்டைக்கா", "வெண்டைக்காய்"),
        ("பொடலங்கா", "புடலங்காய்"),
        ("அவரக்கா", "அவரைக்காய்"),
        ("சுரக்கா", "சுரைக்காய்"),
    ]
    assert len(pairs) == 6
    for spoken, canonical in pairs:
        assert norm(spoken) == norm(canonical), (spoken, canonical)
    assert norm("Sev Vazhai") == "sev vazhai"
    assert norm("") == ""


# --- 3. red banana ------------------------------------------------------------

def test_item_zero_is_the_red_banana():
    first = items_b()[0]
    assert (first.name_en, first.variety) == ("banana", "red")
    assert local_title(first.name_local, first.variety, first.name_en,
                       "ta") == "செவ்வாழை"
    assert english_title(first.name_en, first.variety) == "red banana"
    assert first.proof.quote == EXPECTED_QUOTES[0]
    assert lines(first) == expected(0)


def test_spoken_name_collapses_merged_repeats_and_drops_so():
    from app.pipeline.names import alias_hit_in_text, collapse_repeated_runs
    from app.pipeline.spoken import spoken_item_name

    assert collapse_repeated_runs("vazhaiwazhai") == "vazhai"
    assert alias_hit_in_text("sev vazhaiwazhai") == ("banana", "red")
    assert spoken_item_name(
        "so, sev vazhaiwazhai இன்னைக்கு rate நூற்றி பத்து ரூபா கிலோ"
    ) == "sev vazhai"
    assert spoken_item_name("செவ்வாழை செவ்வாழை அஞ்சு பீஸ் நூறு") == "செவ்வாழை"


# --- 4a. Mannur returned: second line on beans --------------------------------

def test_variant_a_beans_has_two_price_lines():
    items = items_a()
    assert len(items) == 16
    assert all("மன்னூர்" not in (item.name_local or "") for item in items)
    beans = items[10]
    assert (beans.name_en, beans.variety) == ("beans", "mannur")
    assert lines(beans) == expected(10) + [
        (Decimal(70), Decimal(1),
         "kg")]
    assert "மன்னூர்ல" in beans.proof.quote
    assert 3 in beans.proof.turn_ids
    codes = [flag.code for flag in check_item(beans, {}, language="ta")]
    assert "MULTI_PRICE_UNCLEAR" not in codes
    assert "NOT_HEARD" not in codes


def test_variant_a_mannur_echoes_also_fold():
    from app.pipeline.extract import parse_extract_json

    data = payload()
    for name_en in ("mannur", "beans"):
        echo = dict(data["mannur_item"], name_en=name_en)
        model = {"items": data["items"][:11] + [echo] + data["items"][11:]}
        items = parse_extract_json(model, live_transcript(), language="ta")
        assert len(items) == 16, name_en
        beans = items[10]
        assert beans.name_en == "beans", name_en
        assert [line.price for line in beans.price_lines] == [
            Decimal(35),
            Decimal(70)], name_en


def test_variant_a_coverage_adds_nothing():
    from app.pipeline.coverage import add_missed_price_items

    items = items_a()
    assert add_missed_price_items(items, live_transcript(),
                                  language="ta") == items


# --- 4b. Mannur skipped: MISSED_PRICE safety net ------------------------------

def test_variant_b_missed_price_item():
    items = items_b()
    assert len(items) == 17
    missed = items[11]
    assert (missed.name_local, missed.name_en, missed.variety) == (
        "", "other", None)
    assert lines(missed) == [
        (Decimal(70), Decimal(1),
         "kg")]
    assert missed.price_lines[0].said == "எழுபது ஒரு கிலோ"
    assert missed.proof.quote == TURN_3_TEXT
    assert missed.proof.turn_ids == [3]
    assert (missed.proof.start_ms, missed.proof.end_ms) == (39020, 41340)
    (flag,) = [f for f in missed.flags if f.code == "MISSED_PRICE"]
    assert flag.blocking is True
    assert flag.message == (
        "We heard ₹70 here — 'மன்னூர்ல இன்னைக்கு ரேட்டு எழுபது ஒரு கிலோ.'."
        " Which item is it?")
    assert flag.options == ["beans", "Remove"]


def test_coverage_silent_when_everything_is_covered():
    import test_task156
    from test_task136 import stall_transcript

    from app.pipeline.coverage import add_missed_price_items
    from app.pipeline.extract import parse_extract_json

    parsed_156 = test_task156.parsed_items()
    assert add_missed_price_items(
        parsed_156, test_task156.owner2_transcript(),
        language="ta") == parsed_156
    model_1 = json.loads((Path(__file__).resolve().parent / "fixtures"
                          / "real_tamil_stall_1_model.json").read_text())
    parsed_1 = parse_extract_json(model_1, stall_transcript(), language="ta")
    assert add_missed_price_items(
        parsed_1, stall_transcript(), language="ta") == parsed_1


def test_coverage_ignores_filler_amounts():
    from app.pipeline.coverage import find_price_phrases

    assert find_price_phrases("ஒரு கிலோ") == []
    assert find_price_phrases("kaal kilo") == []
    assert find_price_phrases("") == []
    (phrase,) = find_price_phrases("வெண்டைக்கா ஒரு கிலோ அறுபது")
    assert (phrase.price, phrase.per_amount, phrase.unit) == (
        Decimal(60), Decimal(1),
        "kg")


# --- 5. glossary: poosani is ash gourd ----------------------------------------

def test_yellow_and_white_pumpkin_glossary():
    from app.pipeline.names import find_name_in_text, resolve_name

    assert resolve_name("poosani") == ("ash gourd", None)
    assert find_name_in_text("பூசணி") == "ash gourd"
    assert find_name_in_text("பூசணிக்காய்") == "ash gourd"
    assert resolve_name("parangi") == ("pumpkin", None)
    assert find_name_in_text("மஞ்சள் பூசணி") == "pumpkin"
    assert find_name_in_text("பரங்கிக்காய்") == "pumpkin"


# --- 6. the other sixteen prices are untouched ---------------------------------

def test_all_other_prices_and_quotes_unchanged():
    items = items_a()
    for index in list(range(10)) + list(range(11, 16)):
        assert lines(items[index]) == expected(index), index
    assert [item.proof.quote for item in items[:10]] == EXPECTED_QUOTES[:10]
    assert [item.proof.quote for item in items[11:]] == EXPECTED_QUOTES[11:]
    assert items[10].proof.quote.startswith(EXPECTED_QUOTES[10])
    assert all(item.qty is None for item in items)


# --- 7. user-facing strings ----------------------------------------------------

def test_missed_price_message_is_translated():
    from app.web.i18n import flag_text, t_for

    class _Flag:
        code = "MISSED_PRICE"
        field = "name"
        message = ("We heard ₹70 here — 'மன்னூர்ல இன்னைக்கு ரேட்டு "
                   "எழுபது ஒரு கிலோ.'. Which item is it?")
        options = ("beans", "Remove")

    assert flag_text(_Flag(), "en") == _Flag.message
    assert "₹70" in flag_text(_Flag(), "ta")
    assert "எந்தப் பொருள்" in flag_text(_Flag(), "ta")
    assert "₹70" in flag_text(_Flag(), "hi")
    assert "कौन-सी चीज़" in flag_text(_Flag(), "hi")
    assert t_for("en")("review.missed_pick_name")
    assert t_for("ta")("review.missed_pick_name")
    assert t_for("hi")("review.missed_pick_name")


def test_missed_card_shows_needs_you_and_remove(tmp_path):
    from test_task57 import create_shop, make_client, seed_review_session, token_of

    items = items_b()
    missed = items[11]
    missed.flags = [f for f in missed.flags if f.code == "MISSED_PRICE"]
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [items[10], missed])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Needs you" in html
    assert 'data-needs="1"' in html
    assert 'data-value="Remove"' in html
    assert "✕ Remove" in html
    assert 'data-value="beans"' in html
    assert "Which item is it?" in html


def test_approve_removed_card_drops_that_draft(tmp_path):
    import json as jsonlib

    from test_task57 import create_shop, make_client, seed_review_session, token_of

    from app import db

    items = items_b()
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [items[10], items[11]])
    beans_json = jsonlib.loads(db._draft_to_json(items[10]))
    response = client.post(f"/e/{token}/s/{session_id}/approve",
                           json={"items": [beans_json], "confirmed": [0],
                                 "removed": [1]})
    assert response.status_code in (302, 303), response.text
    conn = db.connect(tmp_path / "data")
    try:
        shop_id = conn.execute("SELECT id FROM shops").fetchone()["id"]
        version_id = db.latest_version(conn, shop_id)
        assert [it.name_en for it in db.version_items(conn, version_id)] == [
            "beans"]
    finally:
        conn.close()


def test_approve_rejects_a_tick_without_a_name(tmp_path):
    import json as jsonlib

    from test_task57 import create_shop, make_client, seed_review_session, token_of

    from app import db

    items = items_b()
    client = make_client(tmp_path)
    token = token_of(create_shop(client))
    session_id = seed_review_session(tmp_path, token, [items[10], items[11]])
    body = {"items": [jsonlib.loads(db._draft_to_json(item))
                      for item in (items[10], items[11])],
            "confirmed": [0, 1]}
    response = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"] == (
        "One price still needs a name — pick one or remove it.")
    assert payload["needs_confirm"][0]["index"] == 1


def test_remove_tap_drops_the_card_in_the_browser():
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node, "node is required"
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run([node, "tests/js/review_missed_remove.test.mjs"],
                          cwd=root, check=False, capture_output=True,
                          text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
