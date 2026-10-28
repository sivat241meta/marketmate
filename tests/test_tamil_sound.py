from decimal import Decimal
from pathlib import Path

from app.models import DraftItem, PriceLine, Proof
from app.pipeline.checks import (
    TAMIL_HALF_WORDS,
    TAMIL_SIX_WORDS,
    check_item,
)
from app.pipeline.numbers import find_numbers, parse_number


def pl(price, per_amount, unit):
    return PriceLine(
        Decimal(price) if price is not None else None,
        Decimal(per_amount) if per_amount is not None else None,
        unit,
        "",
    )


def draft(quote="", lines=(), name_en="ginger", qty=None, qty_unit=None):
    return DraftItem(
        name_spoken=name_en,
        name_local=name_en,
        name_en=name_en,
        variety=None,
        price_lines=list(lines),
        qty=Decimal(qty) if qty is not None else None,
        qty_unit=qty_unit,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0),
    )


def flags_by_code(item, previous=None):
    return {f.code: f for f in check_item(item, previous or {})}


def test_numbers_romanised_fifty_eighty():
    assert find_numbers("ambadhu rupa") == [(50, "tamil")]
    assert find_numbers("aimbadhu") == [(50, "tamil")]
    assert find_numbers("nootri ambadhu") == [(150, "tamil")]
    for said in ["aimbadhu", "aimbathu", "ambadhu", "ambathu"]:
        assert parse_number(said) == 50, said
    for said in ["enbadhu", "enbathu", "embadhu", "embathu", "yenbadhu"]:
        assert parse_number(said) == 80, said


def test_live_ginger_180_blocking_sound_alike():
    quote = "இது இஞ்சி இது ஒரு ஒரு கிலோ நூற்றி எம்பது ரூபாய்"
    item = draft(quote=quote, lines=[pl(180, 1, "kg")])
    flags = check_item(item, {})
    flag = next(f for f in flags if f.code == "SOUND_ALIKE")
    assert flag.options == ["150", "180"]
    assert flag.blocking is True
    assert flag.message == "did you say 150 or 180? (50 and 80 sound alike in Tamil)"


def test_tamil_fifty_150_sound_alike():
    item = draft(quote="நூற்றி அம்பது ரூபாய்", lines=[pl(150, 1, "kg")])
    flag = next(f for f in check_item(item, {}) if f.code == "SOUND_ALIKE")
    assert flag.options == ["150", "180"]


def test_romanised_fifty_50_sound_alike():
    item = draft(quote="ambadhu rupa", lines=[pl(50, 1, "kg")], name_en="tomato")
    flag = next(f for f in check_item(item, {}) if f.code == "SOUND_ALIKE")
    assert flag.options == ["50", "80"]


def test_edited_to_alternative_no_not_heard():
    quote = "இது இஞ்சி இது ஒரு ஒரு கிலோ நூற்றி எம்பது ரூபாய்"
    item = draft(quote=quote, lines=[pl(150, 1, "kg")])
    codes = [f.code for f in check_item(item, {})]
    assert "NOT_HEARD" not in codes
    assert "SOUND_ALIKE" in codes


def test_english_alternative_no_not_heard():
    item = draft(quote="tomato eighteen rupees", lines=[pl(80, 1, "kg")],
                 name_en="tomato")
    codes = [f.code for f in check_item(item, {})]
    assert "NOT_HEARD" not in codes
    assert "SOUND_ALIKE" in codes


def test_tamil_previous_150_blocking():
    quote = "இது இஞ்சி இது ஒரு ஒரு கிலோ நூற்றி எம்பது ரூபாய்"
    previous = {"ginger": pl(150, 1, "kg")}
    item = draft(quote=quote, lines=[pl(180, 1, "kg")])
    flag = next(f for f in check_item(item, previous) if f.code == "SOUND_ALIKE")
    assert flag.blocking is True


def test_tamil_previous_180_non_blocking():
    quote = "இது இஞ்சி இது ஒரு ஒரு கிலோ நூற்றி எம்பது ரூபாய்"
    previous = {"ginger": pl(180, 1, "kg")}
    item = draft(quote=quote, lines=[pl(180, 1, "kg")])
    flag = next(f for f in check_item(item, previous) if f.code == "SOUND_ALIKE")
    assert flag.blocking is False


def test_sixty_not_tamil_sound_alike():
    item = draft(quote="தக்காளி அறுபது ரூபாய்", lines=[pl(60, 1, "kg")],
                 name_en="tomato")
    assert not [f for f in check_item(item, {}) if f.code == "SOUND_ALIKE"]


def test_half_six_word_sets():
    assert "அரை" in TAMIL_HALF_WORDS
    assert "arai" in TAMIL_HALF_WORDS
    assert "ara" in TAMIL_HALF_WORDS
    assert "ஆறு" in TAMIL_SIX_WORDS
    assert "aaru" in TAMIL_SIX_WORDS
    assert "aru" in TAMIL_SIX_WORDS


def test_half_six_per_amount_blocking():
    quote = "இந்த வங்காயம் ஆறு கிலோ பதினஞ்சு ரூபா"
    item = draft(quote=quote, lines=[pl(15, 6, "kg")], name_en="small onion")
    flag = next(
        f for f in check_item(item, {})
        if f.code == "SOUND_ALIKE" and f.field == "per_amount"
    )
    assert flag.options == ["0.5", "6"]
    assert flag.blocking is True
    assert flag.message == (
        "did you say half a kg or 6 kg? (arai and aaru sound alike in Tamil)"
    )


def test_half_six_previous_half_still_blocking():
    quote = "இந்த வங்காயம் ஆறு கிலோ பதினஞ்சு ரூபா"
    previous = {"small onion": pl(15, "0.5", "kg")}
    item = draft(quote=quote, lines=[pl(15, 6, "kg")], name_en="small onion")
    flag = next(
        f for f in check_item(item, previous)
        if f.code == "SOUND_ALIKE" and f.field == "per_amount"
    )
    assert flag.options == ["0.5", "6"]
    assert flag.blocking is True


def test_half_kilo_half_amount_no_flag():
    quote = "இந்த வங்காயம் அரை கிலோ பதினைந்து ரூபா"
    item = draft(quote=quote, lines=[pl(15, "0.5", "kg")], name_en="small onion")
    assert not [
        f for f in check_item(item, {})
        if f.code == "SOUND_ALIKE" and f.field == "per_amount"
    ]


def test_review_template_option_targets_per_field():
    template = Path("app/web/templates/review.html").read_text(encoding="utf-8")
    assert 'data-field="per_amount"' in template or "{{ flag.field }}" in template
    js = Path("app/web/static/review.js").read_text(encoding="utf-8")
    assert "dataset.targetField" in js
