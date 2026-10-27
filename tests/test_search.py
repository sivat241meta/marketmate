"""Task 16: customer search and compare (text and voice)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.market.search import (
    Query,
    Want,
    build_query_messages,
    find_listings,
    parse_query,
    parse_query_json,
)
from app.models import DraftItem, PriceLine, Proof, Transcript, Turn
from app.pipeline.names import CANONICAL_NAMES
from app.web.main import create_app

QUOTE = "market secret quote tomato twenty"
CLIP = "/tmp/clips/market_item_0.m4a"
HINT = "market-condition-hint-marks"


def draft(name_en, price, per_amount=1, unit="kg", variety=None):
    return DraftItem(
        name_spoken=name_en,
        name_ta=CANONICAL_NAMES[name_en],
        name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None,
        qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[1], start_ms=0, end_ms=1000,
                    audio_clip=CLIP),
        condition_hint=HINT,
    )


def make_shop(conn, name, area="Koyambedu", listed=True, is_demo=False,
              is_judge=False):
    return db.create_shop(
        conn, name=name, phone="+914400000000", area=area,
        language="ta", currency="INR", shop_type="vegetable",
        is_demo=is_demo, is_judge=is_judge, listed=listed)


def publish(conn, shop_id, drafts):
    session_id = db.create_session(conn, shop_id, "video")
    version_id = db.approve(conn, session_id, drafts)
    db.set_published(conn, version_id, True)
    return version_id


def age_version(conn, version_id, hours):
    old = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    conn.execute("UPDATE versions SET created_at = ? WHERE id = ?",
                 (old, version_id))
    conn.commit()


def seed_two_shops(tmp_path):
    """Cheap fresh demo shop A (tomato 18) + pricey fresh shop B (tomato 30)."""
    conn = db.connect(tmp_path / "data")
    try:
        a_id, a_slug, _ = make_shop(conn, "Demo Stall A", is_demo=True)
        b_id, b_slug, _ = make_shop(conn, "Stall B")
        publish(conn, a_id, [draft("tomato", 18)])
        publish(conn, b_id, [draft("tomato", 30), draft("onion", 25)])
    finally:
        conn.close()
    return a_slug, b_slug


# --- parse_query: Spark JSON -> Query ---

def test_parse_query_tomato_under_25_uses_low_reasoning(monkeypatch, tmp_path):
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return {"wants": [{"name": "tomato", "amount": None, "unit": None,
                           "max_rate": 25}],
                "budget": None, "area": None}

    monkeypatch.setattr("app.market.search.chat_json", fake_chat_json)
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    query = parse_query("tomato under 25", ledger=ledger, settings=settings)
    assert seen["kwargs"]["reasoning_effort"] == "low"
    assert query.wants == [Want("tomato", None, None, Decimal(25))]
    assert query.budget is None and query.area is None


def test_parse_query_synonym_shallot_finds_small_onion():
    query = parse_query_json(
        {"wants": [{"name": "shallot", "amount": None, "unit": None,
                    "max_rate": None}],
         "budget": None, "area": None})
    assert [w.name_en for w in query.wants] == ["small onion"]
    assert query.unknown == []


def test_parse_query_drops_unknown_names():
    query = parse_query_json(
        {"wants": [{"name": "tomato", "amount": 2, "unit": "kg",
                    "max_rate": None},
                   {"name": "dragonfruit", "amount": None, "unit": None,
                    "max_rate": None}],
         "budget": None, "area": None})
    assert query.wants == [Want("tomato", Decimal(2), "kg", None)]
    assert query.unknown == ["dragonfruit"]


def test_parse_query_budget_and_area():
    query = parse_query_json(
        {"wants": [{"name": "tomato", "amount": 1, "unit": "kg",
                    "max_rate": None}],
         "budget": 300, "area": "Anna Nagar"})
    assert query.budget == Decimal(300)
    assert query.area == "Anna Nagar"


def test_prompt_contains_query_text():
    messages = build_query_messages("tomato under 25 please")
    assert "tomato under 25 please" in messages[-1]["content"]
    assert "tomato" in messages[-1]["content"]


# --- find_listings: DB -> sorted listings ---

def test_max_rate_filters_by_per_kg_rate(tmp_path):
    seed_two_shops(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        listings = find_listings(
            conn, Query([Want("tomato", None, None, Decimal(25))], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    assert [row.shop_name for row in listings] == ["Demo Stall A"]
    assert listings[0].rate == Decimal(18)
    assert listings[0].rate_unit == "kg"


def test_rate_compares_quarter_kilo_line(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        a_id, _, _ = make_shop(conn, "Shop Q")
        b_id, _, _ = make_shop(conn, "Shop K")
        publish(conn, a_id, [draft("tomato", 15, 250, "g")])
        publish(conn, b_id, [draft("tomato", 40)])
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    by_shop = {row.shop_name: row for row in listings}
    assert by_shop["Shop Q"].rate == Decimal(60)
    assert by_shop["Shop K"].rate == Decimal(40)
    assert [row.shop_name for row in listings] == ["Shop K", "Shop Q"]


def test_stale_listing_marked_and_sorts_last(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        old_id, _, _ = make_shop(conn, "Old Cheap")
        fresh_id, _, _ = make_shop(conn, "Fresh Pricy")
        old_vid = publish(conn, old_id, [draft("tomato", 10)])
        publish(conn, fresh_id, [draft("tomato", 20)])
        age_version(conn, old_vid, 30)
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    assert [row.shop_name for row in listings] == ["Fresh Pricy", "Old Cheap"]
    assert [row.stale for row in listings] == [False, True]


def test_unlisted_judge_shop_never_appears(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        judge_id, _, _ = make_shop(conn, "Judge Test", is_judge=True,
                                   listed=False)
        listed_id, _, _ = make_shop(conn, "Listed Stall")
        publish(conn, judge_id, [draft("tomato", 5)])
        publish(conn, listed_id, [draft("tomato", 18)])
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    assert [row.shop_name for row in listings] == ["Listed Stall"]


def test_unpublished_shop_never_appears(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn, "Unpublished Stall")
        session_id = db.create_session(conn, shop_id, "video")
        db.approve(conn, session_id, [draft("tomato", 5)])
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    assert listings == []


def test_sold_out_item_excluded(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn, "Sold Out Stall")
        version_id = publish(conn, shop_id, [draft("tomato", 5)])
        item_id = db.version_items(conn, version_id)[0].id
        db.set_sold_out(conn, item_id, True)
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, None),
            datetime.now(UTC))
    finally:
        conn.close()
    assert listings == []


def test_area_filters_case_insensitive(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        a_id, _, _ = make_shop(conn, "Anna Shop", area="Anna Nagar")
        k_id, _, _ = make_shop(conn, "Koya Shop", area="Koyambedu")
        publish(conn, a_id, [draft("tomato", 18)])
        publish(conn, k_id, [draft("tomato", 18)])
        listings = find_listings(
            conn, Query([Want("tomato", None, None, None)], None, "anna"),
            datetime.now(UTC))
    finally:
        conn.close()
    assert [row.shop_name for row in listings] == ["Anna Shop"]


# --- /market pages ---

def make_client(tmp_path, monkeypatch):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    return TestClient(create_app(settings), follow_redirects=False)


def test_market_page_has_search_and_voice_recorder(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    html = client.get("/market").text
    assert 'name="q"' in html
    assert "recorder.js" in html
    assert "/market/voice" in html
    assert 'name="audio"' in html


def test_market_results_badges_links_and_no_proof(tmp_path, monkeypatch):
    a_slug, b_slug = seed_two_shops(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        b_shop = conn.execute("SELECT id FROM shops WHERE slug = ?",
                              (b_slug,)).fetchone()["id"]
        b_vid = db.latest_version(conn, b_shop, published_only=True)
        age_version(conn, b_vid, 30)
    finally:
        conn.close()

    def fake_parse_query(text, **kwargs):
        assert text == "tomato"
        return Query([Want("tomato", None, None, None)], None, None)

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    client = make_client(tmp_path, monkeypatch)
    html = client.get("/market", params={"q": "tomato"}).text
    assert "Demo data" in html
    assert "may be old" in html
    assert f"/s/{a_slug}" in html and f"/s/{b_slug}" in html
    assert "₹18" in html and "₹30" in html
    assert QUOTE not in html
    assert "/clip/" not in html
    assert CLIP not in html
    assert HINT not in html


def test_market_page_names_unknown_words(tmp_path, monkeypatch):
    seed_two_shops(tmp_path)

    def fake_parse_query(text, **kwargs):
        return Query([], None, None, unknown=["dragonfruit"])

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    client = make_client(tmp_path, monkeypatch)
    html = client.get("/market", params={"q": "dragonfruit"}).text
    assert "dragonfruit" in html
    assert "understood" in html.lower()


def test_market_voice_converts_audio_then_searches(tmp_path, monkeypatch):
    a_slug, _ = seed_two_shops(tmp_path)
    calls = {}

    def fake_extract_audio(src, out_wav):
        calls["extract_audio"] = str(src)
        out = Path(out_wav)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"RIFF-fake-wav")
        return out

    def fake_transcribe(wav, **kwargs):
        assert calls["extract_audio"].endswith(".webm")
        calls["transcribe"] = str(wav)
        return Transcript(
            text="tomato under 25", duration_ms=2000,
            turns=[Turn(id=1, start_ms=0, end_ms=2000,
                        text="tomato under 25")])

    def fake_parse_query(text, **kwargs):
        assert text == "tomato under 25"
        calls["query"] = text
        return Query([Want("tomato", None, None, Decimal(25))], None, None)

    monkeypatch.setattr("app.web.main.extract_audio", fake_extract_audio)
    monkeypatch.setattr("app.web.main.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/market/voice",
        files={"audio": ("search.webm", b"fake-opus", "audio/webm")})
    assert response.status_code == 200
    assert calls["transcribe"].endswith(".wav")
    assert f"/s/{a_slug}" in response.text
    assert "₹18" in response.text
    assert "₹30" not in response.text
