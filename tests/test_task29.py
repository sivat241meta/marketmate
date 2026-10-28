"""Task 29: 25 Muse Voice languages, digit and cross-checked number proof."""

import sqlite3
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.languages import LANGUAGES, by_api_name, get_language, language_bias
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.checks import check_item
from app.pipeline.numbers import find_numbers, normalise_digits, parse_number

EXPECTED_API_NAMES = {
    "Arabic", "Bengali", "Dutch", "English", "French", "German", "Hebrew",
    "Hindi", "Indonesian", "Italian", "Japanese", "Kannada", "Korean",
    "Malay", "Mandarin Chinese", "Marathi", "Polish", "Portuguese",
    "Spanish", "Tagalog", "Tamil", "Telugu", "Thai", "Turkish",
    "Vietnamese",
}

EXPECTED_CODES = {
    "ar", "bn", "nl", "en", "fr", "de", "he", "hi", "id", "it", "ja",
    "kn", "ko", "ms", "zh", "mr", "pl", "pt", "es", "tl", "ta", "te",
    "th", "tr", "vi",
}

EXPECTED_CURRENCIES = {
    "en": "INR", "ta": "INR", "hi": "INR", "bn": "INR", "te": "INR",
    "kn": "INR", "mr": "INR", "ar": "AED", "nl": "EUR", "fr": "EUR",
    "de": "EUR", "it": "EUR", "es": "EUR", "he": "ILS", "id": "IDR",
    "ja": "JPY", "ko": "KRW", "ms": "MYR", "zh": "CNY", "pl": "PLN",
    "pt": "BRL", "tl": "PHP", "th": "THB", "tr": "TRY", "vi": "VND",
}


def test_registry_has_exactly_25_unique():
    assert len(LANGUAGES) == 25
    assert {lang.code for lang in LANGUAGES} == EXPECTED_CODES
    assert {lang.api_name for lang in LANGUAGES} == EXPECTED_API_NAMES
    assert len({lang.code for lang in LANGUAGES}) == 25
    assert len({lang.api_name for lang in LANGUAGES}) == 25


def test_registry_currencies_and_words():
    for lang in LANGUAGES:
        assert lang.default_currency == EXPECTED_CURRENCIES[lang.code]
        assert isinstance(lang.currency_words, tuple)
        assert len(lang.currency_words) >= 1
        assert isinstance(lang.decimal_comma, bool)
        assert lang.native_name
        assert lang.script


def test_get_language_and_by_api_name():
    assert get_language("ta").api_name == "Tamil"
    assert get_language("hi").api_name == "Hindi"
    assert by_api_name("Tamil").code == "ta"
    assert by_api_name("Mandarin Chinese").code == "zh"
    with pytest.raises(KeyError):
        get_language("xx")


def test_language_bias():
    assert language_bias("ta") == ["Tamil", "English"]
    assert language_bias("hi") == ["Hindi", "English"]
    assert language_bias("fr") == ["French", "English"]
    assert language_bias("en") == ["English"]


@pytest.mark.parametrize("said,val", [
    ("18", "18"),
    ("१८", "18"),  # Devanagari
    ("১৮", "18"),  # Bengali
    ("௧௮", "18"),  # Tamil
    ("౧౮", "18"),  # Telugu
    ("೧೮", "18"),  # Kannada
    ("١٨", "18"),  # Arabic-Indic
    ("๑๘", "18"),  # Thai
])
def test_normalise_digits_scripts(said, val):
    assert normalise_digits(said) == val


def test_normalise_digits_separators():
    assert normalise_digits("15,000") == "15000"
    assert normalise_digits("15,000", decimal_comma=True) == "15.000"
    assert normalise_digits("15.000", decimal_comma=True) == "15000"
    assert normalise_digits("15 000") == "15000"
    assert normalise_digits("15 000", decimal_comma=True) == "15000"
    assert normalise_digits("18.50") == "18.50"


def test_digits_in_any_script_count_as_heard():
    assert parse_number("१८") == 18
    assert parse_number("๑๘") == 18
    assert find_numbers("tamatar १८ rupaye") == [(18, "digits")]
    assert find_numbers("tomato 15,000 rupees") == [(15000, "digits")]


@pytest.mark.parametrize("said,val", [
    ("chaalis", 40),
    ("चालीस", 40),
    ("pachchees", 25),
    ("पच्चीस", 25),
    ("dedh sau", 150),
    ("डेढ़ सौ", 150),
    ("dhaai", Decimal("2.5")),
    ("ढाई", Decimal("2.5")),
    ("sau", 100),
    ("सौ", 100),
    ("hazaar", 1000),
    ("हज़ार", 1000),
    ("dedh", Decimal("1.5")),
    ("dhai", Decimal("2.5")),
])
def test_hindi_parser(said, val):
    assert parse_number(said) == val


def test_hindi_find_numbers_kind():
    assert find_numbers("tamatar chaalis rupaye")[0] == (40, "hindi")
    assert find_numbers("टमाटर चालीस रुपये")[0] == (40, "hindi")


def _draft(quote, price, said, name_en="tomato"):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg", said)],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[], start_ms=0, end_ms=0),
    )


def _ledger_settings(tmp_path, baseten=False):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    env = {"MODEL_API_KEY": "k"}
    if baseten:
        env["BASETEN_API_KEY"] = "b"
    return ledger, load_settings(env)


def test_cross_check_agree_no_flag(tmp_path, monkeypatch):
    from app.pipeline import checks as checks_mod

    ledger, settings = _ledger_settings(tmp_path)
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return {"value": 40}

    monkeypatch.setattr(checks_mod, "chat_json", fake_chat_json)
    item = _draft("tomate quarante euros", 40, "quarante")
    flags = check_item(item, {}, language="fr", ledger=ledger,
                       settings=settings)
    assert "NUMBER_CHECK" not in [f.code for f in flags]
    assert "NOT_HEARD" not in [f.code for f in flags]
    assert item.proof.number_check == "cross-checked"
    # Only the quoted phrase and the language name go to the model.
    blob = str(seen["messages"])
    assert "quarante" in blob and "French" in blob
    assert seen["kwargs"]["reasoning_effort"] == "low"


def test_cross_check_disagree_number_check(tmp_path, monkeypatch):
    from app.pipeline import checks as checks_mod

    ledger, settings = _ledger_settings(tmp_path)
    monkeypatch.setattr(checks_mod, "chat_json",
                        lambda messages, **kw: {"value": 50})
    item = _draft("tomate quarante euros", 40, "quarante")
    flags = check_item(item, {}, language="fr", ledger=ledger,
                       settings=settings)
    flag = next(f for f in flags if f.code == "NUMBER_CHECK")
    assert flag.blocking is True
    assert "not sure about this number" in flag.message
    assert set(flag.options) == {"40", "50"}


def test_cross_check_failure_number_check(tmp_path, monkeypatch):
    from app.pipeline import checks as checks_mod

    def boom(messages, **kwargs):
        raise RuntimeError("down")

    ledger, settings = _ledger_settings(tmp_path)
    monkeypatch.setattr(checks_mod, "chat_json", boom)
    item = _draft("tomate quarante euros", 40, "quarante")
    flags = check_item(item, {}, language="fr", ledger=ledger,
                       settings=settings)
    flag = next(f for f in flags if f.code == "NUMBER_CHECK")
    assert flag.blocking is True


def test_cross_check_uses_baseten_when_key_set(tmp_path, monkeypatch):
    from app.pipeline import checks as checks_mod

    ledger, settings = _ledger_settings(tmp_path, baseten=True)
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["kwargs"] = kwargs
        return {"value": 40}

    monkeypatch.setattr(checks_mod, "chat_json", fake_chat_json)
    item = _draft("tomate quarante euros", 40, "quarante")
    check_item(item, {}, language="fr", ledger=ledger, settings=settings)
    assert seen["kwargs"]["provider"] == "baseten"


def test_hindi_sound_alike_saath_saat():
    item = _draft("tamatar saath rupaye", 60, "saath")
    flag = next(f for f in check_item(item, {}) if f.code == "SOUND_ALIKE")
    assert set(flag.options) == {"7", "60"}
    item2 = _draft("टमाटर साठ रुपये", 60, "साठ")
    assert any(f.code == "SOUND_ALIKE" for f in check_item(item2, {}))


def test_name_local_migration_keeps_data(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = sqlite3.connect(data_dir / "marketmate.db")
    conn.execute(
        "CREATE TABLE shops (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " slug TEXT, name TEXT, phone TEXT, area TEXT, language TEXT,"
        " currency TEXT, type TEXT, edit_token_hash TEXT, created_at TEXT)")
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER, kind TEXT, status TEXT, message TEXT DEFAULT '',"
        " cost REAL DEFAULT 0, created_at TEXT)")
    conn.execute(
        "CREATE TABLE drafts (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " session_id INTEGER, item_index INTEGER, data TEXT)")
    conn.execute(
        "CREATE TABLE versions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER, created_at TEXT, published INTEGER DEFAULT 0)")
    conn.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " version_id INTEGER, name_ta TEXT NOT NULL, name_en TEXT NOT NULL,"
        " variety TEXT, qty TEXT, qty_unit TEXT, photo TEXT,"
        " sold_out INTEGER DEFAULT 0, proof TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE price_lines (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " item_id INTEGER, price TEXT, per_amount TEXT, unit TEXT,"
        " said TEXT DEFAULT '')")
    conn.execute(
        "CREATE TABLE photo_checks (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER, created_at TEXT, image_path TEXT,"
        " report_json TEXT, cost REAL DEFAULT 0)")
    conn.execute(
        "CREATE TABLE quotes (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " shop_id INTEGER, token TEXT UNIQUE, source TEXT, kind TEXT,"
        " status TEXT, lines_json TEXT, total TEXT, customer_note TEXT,"
        " created_at TEXT, updated_at TEXT)")
    conn.execute(
        "INSERT INTO versions (id, shop_id, created_at, published)"
        " VALUES (1, 1, 'x', 1)")
    conn.execute(
        "INSERT INTO items (version_id, name_ta, name_en, proof)"
        " VALUES (1, 'தக்காளி', 'tomato',"
        " '{\"quote\":\"q\",\"turn_ids\":[1],\"start_ms\":0,"
        " \"end_ms\":1}')")
    conn.commit()
    conn.close()
    conn = db.connect(data_dir)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
        assert "name_local" in cols
        assert "name_ta" not in cols
        items = db.version_items(conn, 1)
        assert items[0].name_local == "தக்காளி"
    finally:
        conn.close()


def test_shop_form_lists_25_languages(tmp_path, monkeypatch):
    from app.web.main import create_app

    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    html = client.get("/new").text
    for code in EXPECTED_CODES:
        assert f'value="{code}"' in html, code
    assert "தமிழ்" in html and "हिन्दी" in html
    # Registry currencies are offered too.
    for currency in ("INR", "EUR", "JPY", "THB", "BRL"):
        assert currency in html


def test_i18n_strings(tmp_path):
    from app.web.i18n import get_strings

    en = get_strings("en")
    ta = get_strings("ta")
    hi = get_strings("hi")
    assert len(en) >= 25 and len(ta) >= 25 and len(hi) >= 25
    assert set(ta) == set(en) == set(hi)
    # Other languages fall back to English.
    assert get_strings("fr") == en
