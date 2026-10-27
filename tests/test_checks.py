import json
from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, PriceLine, Proof
from app.pipeline.checks import SOUND_ALIKE_PAIRS, WEIGHT_ITEMS, check_item


def pl(price, per_amount, unit, said=""):
    return PriceLine(
        Decimal(price) if price is not None else None,
        Decimal(per_amount) if per_amount is not None else None,
        unit,
        said,
    )


def draft(quote="", lines=(), name_en="tomato", qty=None, qty_unit=None, **kwargs):
    return DraftItem(
        name_spoken=kwargs.get("name_spoken", name_en),
        name_ta=kwargs.get("name_ta", name_en),
        name_en=name_en,
        variety=kwargs.get("variety"),
        price_lines=list(lines),
        qty=Decimal(qty) if qty is not None else None,
        qty_unit=qty_unit,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0),
        range_said=kwargs.get("range_said", False),
    )


def codes(item, previous=None):
    return [f.code for f in check_item(item, previous or {})]


def live_potato_quote():
    data = json.loads(Path("tests/fixtures/transcribe_live_mixed.json").read_text())
    turn_text = data["turns"][0]["transcript"]
    return turn_text[turn_text.index("urulaikizhangu"):]


def test_not_heard_price():
    item = draft(quote="thakkali", lines=[pl(18, 1, "kg")])
    assert "NOT_HEARD" in codes(item)


def test_real_ginger_quote_hears_150():
    # Quote copied from eval/out/real1.json (gitignored run output).
    quote = "இது இஞ்சி இது ஒரு கிலோ நூற்று அம்பது ரூபா"
    item = draft(quote=quote, lines=[pl(150, 1, "kg")], name_en="ginger")
    found = codes(item)
    assert "NOT_HEARD" not in found
    assert "UNCLEAR_NUMBER" not in found


def test_real_small_onion_quote_hears_15():
    # Quote copied from eval/out/real1.json (gitignored run output).
    quote = "இந்த வங்காயம் அரை கிலோ பதினைந்து ரூபா சின்ன வங்காயம்"
    item = draft(quote=quote, lines=[pl(15, "0.5", "kg")], name_en="small onion")
    found = codes(item)
    assert "NOT_HEARD" not in found
    assert "UNCLEAR_NUMBER" not in found


def test_not_heard_qty():
    item = draft(quote="thakkali kilo 18", lines=[pl(18, 1, "kg")],
                 qty=40, qty_unit="kg")
    assert "NOT_HEARD" in codes(item)


def test_self_correction_two_prices():
    item = draft(quote="thakkali 18 illa illa 20",
                 lines=[pl(18, 1, "kg"), pl(20, 1, "kg")])
    flag = next(x for x in check_item(item, {}) if x.code == "TWO_PRICES")
    assert flag.options == ["18", "20"]


def test_digits_not_sound_alike():
    item = draft(quote="thakkali 18", lines=[pl(18, 1, "kg")])
    assert not [x for x in check_item(item, {}) if x.code == "SOUND_ALIKE"]


def test_sound_alike_english_options():
    item = draft(quote="tomato eighteen rupees", lines=[pl(18, 1, "kg")])
    flag = next(x for x in check_item(item, {}) if x.code == "SOUND_ALIKE")
    assert flag.options == ["18", "80"]
    assert SOUND_ALIKE_PAIRS[18] == 80


def test_sound_alike_both_directions():
    item = draft(quote="tomato eighty rupees", lines=[pl(80, 1, "kg")])
    flag = next(x for x in check_item(item, {}) if x.code == "SOUND_ALIKE")
    assert flag.options == ["18", "80"]


def test_sound_alike_matching_previous_non_blocking():
    previous = {"tomato": pl(20, 1, "kg")}
    item = draft(quote="tomato eighteen rupees", lines=[pl(18, 1, "kg")])
    flag = next(x for x in check_item(item, previous) if x.code == "SOUND_ALIKE")
    assert flag.blocking is False
    assert "matches the previous price" in flag.message
    assert "18" in flag.message


def test_sound_alike_far_from_previous_blocking():
    previous = {"tomato": pl(75, 1, "kg")}
    item = draft(quote="tomato eighteen rupees", lines=[pl(18, 1, "kg")])
    flag = next(x for x in check_item(item, previous) if x.code == "SOUND_ALIKE")
    assert flag.blocking is True


def test_jump_uses_rate_not_raw_price():
    previous = {"tomato": pl(40, 1, "kg")}
    jumped = draft(quote="tomato kilo sixteen", lines=[pl(16, 250, "g")])
    assert "JUMP" in codes(jumped, previous)
    exact = draft(quote="tomato kilo fifteen", lines=[pl(15, 250, "g")])
    assert "JUMP" not in codes(exact, previous)


def test_jump_message_shows_previous():
    previous = {"tomato": pl(40, 1, "kg")}
    jumped = draft(quote="tomato kilo sixteen", lines=[pl(16, 250, "g")])
    flag = next(x for x in check_item(jumped, previous) if x.code == "JUMP")
    assert "40" in flag.message


def test_clean_item_only_qty_missing():
    item = draft(quote="tomato kilo 18", lines=[pl(18, 1, "kg")])
    assert codes(item) == ["QTY_MISSING"]


def test_unit_missing():
    item = draft(quote="tomato 18", lines=[pl(18, 1, None)])
    assert "UNIT_MISSING" in codes(item)


def test_unit_missing_offers_sibling_unit():
    item = draft(quote="tomato 18", lines=[pl(18, 1, None), pl(20, 1, "kg")])
    flag = next(x for x in check_item(item, {}) if x.code == "UNIT_MISSING")
    assert flag.options == ["per 1 kg"]


def test_unit_odd():
    assert "tomato" in WEIGHT_ITEMS
    item = draft(quote="tomato ten per piece", lines=[pl(10, 1, "piece")])
    assert "UNIT_ODD" in codes(item)


def test_range_flag():
    item = draft(quote="tomato thirty thirty five", lines=[pl(None, 1, "kg")],
                 range_said=True)
    assert "RANGE" in codes(item)


def test_no_price():
    item = draft(quote="thakkali", lines=[])
    assert "NO_PRICE" in codes(item)


def test_correction_said_live_potato():
    quote = live_potato_quote()
    assert "இல்ல" in quote
    item = draft(quote=quote, name_en="potato",
                 lines=[pl(30, 1, "kg"), pl(35, 1, "kg")])
    flags = {f.code: f for f in check_item(item, {})}
    assert "CORRECTION_SAID" in flags
    assert flags["CORRECTION_SAID"].blocking
    assert "TWO_PRICES" in flags


def test_unclear_number_thirupathu():
    item = draft(quote="urulaikizhangu kilo thirupathu rupai",
                 name_en="potato", lines=[pl(30, 1, "kg")])
    flags = {f.code: f for f in check_item(item, {})}
    assert "UNCLEAR_NUMBER" in flags
    assert "thirupathu" in flags["UNCLEAR_NUMBER"].message
    assert flags["UNCLEAR_NUMBER"].blocking


def test_unclear_number_mukpathu():
    item = draft(quote="thengai onnu mukpathu rupai",
                 name_en="coconut", lines=[pl(30, 1, "piece")])
    flags = {f.code: f for f in check_item(item, {})}
    assert "UNCLEAR_NUMBER" in flags
    assert "mukpathu" in flags["UNCLEAR_NUMBER"].message


def test_unclear_number_skips_numbers_and_units():
    item = draft(quote="tomato 18 rupees", lines=[pl(18, 1, "kg")])
    assert "UNCLEAR_NUMBER" not in codes(item)
    item = draft(quote="tomato kilo rupai", lines=[pl(18, 1, "kg")])
    assert "UNCLEAR_NUMBER" not in codes(item)
