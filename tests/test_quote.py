"""Task 27: customer quotation from voice, text or photo (fakes, no network)."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.names import CANONICAL_NAMES

QUOTE = "quote tomato secret"
CLIP = "/tmp/clips/quote_item.m4a"


def draft(name_en, price, per_amount=1, unit="kg", variety=None):
    return DraftItem(
        name_spoken=name_en,
        name_local=CANONICAL_NAMES[name_en],
        name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None,
        qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[1], start_ms=0, end_ms=1000,
                    audio_clip=CLIP),
    )


def make_shop(conn, name="Quote Stall", area="Koyambedu", listed=True):
    return db.create_shop(
        conn, name=name, phone="+914400000001", area=area,
        language="ta", currency="INR", shop_type="vegetable",
        is_demo=False, is_judge=False, listed=listed)


def publish(conn, shop_id, drafts):
    session_id = db.create_session(conn, shop_id, "video")
    version_id = db.approve(conn, session_id, drafts)
    db.set_published(conn, version_id, True)
    return version_id


def seed_standard(conn):
    shop_id, slug, token = make_shop(conn)
    publish(conn, shop_id, [
        draft("tomato", 18, 1, "kg"),
        draft("banana", 60, 1, "dozen"),
        draft("coconut", 15, 1, "piece"),
    ])
    return shop_id, slug, token


@pytest.fixture
def ledger(tmp_path):
    return CostLedger(tmp_path / "c.db", 100.0)


@pytest.fixture
def settings():
    return load_settings({"MODEL_API_KEY": "k"})


def fake_query_json(*, tomato=(2, "kg"), banana=(1, "dozen"),
                   coconut=(3, None), extra=()):
    wants = []
    if tomato is not None:
        wants.append({"name": "tomato", "amount": tomato[0], "unit": tomato[1],
                      "max_rate": None})
    if banana is not None:
        wants.append({"name": "banana", "amount": banana[0], "unit": banana[1],
                      "max_rate": None})
    if coconut is not None:
        wants.append({"name": "coconut", "amount": coconut[0],
                      "unit": coconut[1], "max_rate": None})
    for name, amount, unit in extra:
        wants.append({"name": name, "amount": amount, "unit": unit,
                      "max_rate": None})
    return {"wants": wants, "budget": None, "area": None}


# --- text request ---

def test_text_request_correct_lines_and_total(tmp_path, monkeypatch, ledger,
                                             settings):
    from app.market.quote import build_quote, wanted_from_text

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
    finally:
        pass
    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: __import__(
            "app.market.search", fromlist=["parse_query_json"]
        ).parse_query_json(fake_query_json()))
    wanted = wanted_from_text("2 kg tomato, 1 dozen banana, 3 coconut",
                              ledger=ledger, settings=settings)
    assert [(w.name_en, w.qty, w.unit) for w in wanted] == [
        ("tomato", Decimal(2), "kg"),
        ("banana", Decimal(1), "dozen"),
        ("coconut", Decimal(3), None),
    ]
    quote = build_quote(conn, shop_id, wanted)
    try:
        by_name = {line.name_en: line for line in quote.lines}
        assert by_name["tomato"].status == "priced"
        assert by_name["tomato"].unit_price == Decimal(18)
        assert by_name["tomato"].line_total == Decimal("36.00")
        assert by_name["banana"].line_total == Decimal("60.00")
        assert by_name["coconut"].unit == "piece"
        assert by_name["coconut"].line_total == Decimal("45.00")
        assert quote.total == Decimal("141.00")
        assert quote.priced_count == 3
        assert quote.unpriced_count == 0
        assert quote.prices_set_at is not None
    finally:
        conn.close()


def test_kg_g_conversion(tmp_path, ledger, settings):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn)
        publish(conn, shop_id, [draft("tomato", 15, 250, "g")])
        quote = build_quote(
            conn, shop_id, [WantedLine("tomato", Decimal(1), "kg", "text")])
        assert quote.lines[0].line_total == Decimal("60.00")
        quote2 = build_quote(
            conn, shop_id, [WantedLine("tomato", Decimal(500), "g", "text")])
        assert quote2.lines[0].line_total == Decimal("30.00")
    finally:
        conn.close()


def test_kg_g_conversion_shop_per_kg(tmp_path, ledger, settings):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn)
        publish(conn, shop_id, [draft("tomato", 18, 1, "kg")])
        quote = build_quote(
            conn, shop_id, [WantedLine("tomato", Decimal(500), "g", "text")])
        assert quote.lines[0].line_total == Decimal("9.00")
    finally:
        conn.close()


def test_unknown_item_not_on_list(tmp_path, ledger, settings):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        quote = build_quote(
            conn, shop_id,
            [WantedLine("tomato", Decimal(1), "kg", "text"),
             WantedLine("dragonfruit", Decimal(1), "kg", "text")])
        by_name = {line.name_en: line for line in quote.lines}
        assert by_name["dragonfruit"].status == "not_on_list"
        assert by_name["dragonfruit"].unit_price is None
        assert by_name["dragonfruit"].line_total is None
        assert quote.total == Decimal("18.00")
        assert quote.priced_count == 1
        assert quote.unpriced_count == 1
    finally:
        conn.close()


def test_sold_out_has_no_total(tmp_path, ledger, settings):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        version_id = db.latest_version(conn, shop_id, published_only=True)
        items = db.version_items(conn, version_id)
        tomato_id = next(i.id for i in items if i.name_en == "tomato")
        db.set_sold_out(conn, tomato_id, True)
        quote = build_quote(
            conn, shop_id, [WantedLine("tomato", Decimal(2), "kg", "text")])
        assert quote.lines[0].status == "sold_out"
        assert quote.lines[0].line_total is None
        assert quote.total == Decimal("0.00")
    finally:
        conn.close()


def test_weight_without_qty_needs_qty(tmp_path, ledger, settings):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        quote = build_quote(
            conn, shop_id, [WantedLine("tomato", None, None, "text")])
        line = quote.lines[0]
        assert line.status == "needs_qty"
        assert line.qty == Decimal(1)
        assert line.unit == "kg"
        assert line.unit_price == Decimal(18)
    finally:
        conn.close()


def test_synonym_matches_shop_item(tmp_path, ledger, settings):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn)
        publish(conn, shop_id, [draft("small onion", 30, 1, "kg")])
        quote = build_quote(
            conn, shop_id, [WantedLine("shallot", Decimal(2), "kg", "text")])
        assert quote.lines[0].status == "priced"
        assert quote.lines[0].line_total == Decimal("60.00")
    finally:
        conn.close()


# --- photo path ---

def _jpeg(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), "red").save(path, "JPEG")
    return path


def test_photo_items_use_reconciled_counts(tmp_path, monkeypatch, ledger,
                                           settings):
    from app.market.quote import build_quote, wanted_from_photo
    from app.pipeline.vision import DetectedProduct, PhotoReport

    image = _jpeg(tmp_path / "items.jpg")
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen["vision"] = True
        assert any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for message in messages for part in message.get("content", [])
            if isinstance(message.get("content"), list))
        return {"kind": "items", "products": [
            {"name_en": "coconut", "countable": True},
            {"name_en": "banana", "countable": True}]}

    def fake_analyse(photo, *, shop_items, ledger, settings):
        seen["analyse"] = True
        return PhotoReport(
            products=[
                DetectedProduct(name_en="coconut", countable=True,
                                count_spark=3, count_sam=3, count=3),
                DetectedProduct(name_en="banana", countable=True,
                                count_spark=12, count_sam=12, count=12),
            ],
            quality="good", suggestions=[], cost_usd=0.0)

    monkeypatch.setattr("app.market.quote.chat_json", fake_chat_json)
    monkeypatch.setattr("app.market.quote.analyse_photo", fake_analyse)
    wanted = wanted_from_photo(image, ledger=ledger, settings=settings)
    assert seen.get("vision") and seen.get("analyse")
    assert [(w.name_en, w.qty) for w in wanted] == [
        ("coconut", Decimal(3)), ("banana", Decimal(12))]
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = make_shop(conn)
        publish(conn, shop_id, [
            draft("coconut", 15, 1, "piece"),
            draft("banana", 5, 1, "piece"),
        ])
        quote = build_quote(conn, shop_id, wanted)
        by_name = {line.name_en: line for line in quote.lines}
        assert by_name["coconut"].line_total == Decimal("45.00")
        assert by_name["banana"].line_total == Decimal("60.00")
    finally:
        conn.close()


def test_photo_handwritten_list_reads_lines(tmp_path, monkeypatch, ledger,
                                            settings):
    from app.market.quote import build_quote, wanted_from_photo

    image = _jpeg(tmp_path / "list.jpg")

    def fake_chat_json(messages, **kwargs):
        return {"kind": "shopping_list", "lines": [
            {"name": "tomato", "qty": 2, "unit": "kg"},
            {"name": "banana", "qty": 1, "unit": "dozen"},
            {"name": "coconut", "qty": 3, "unit": None}]}

    def no_analyse(*a, **k):
        raise AssertionError("items engine must not run for a list photo")

    monkeypatch.setattr("app.market.quote.chat_json", fake_chat_json)
    monkeypatch.setattr("app.market.quote.analyse_photo", no_analyse)
    wanted = wanted_from_photo(image, ledger=ledger, settings=settings)
    assert [(w.name_en, w.qty, w.unit) for w in wanted] == [
        ("tomato", Decimal(2), "kg"),
        ("banana", Decimal(1), "dozen"),
        ("coconut", Decimal(3), None),
    ]
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        quote = build_quote(conn, shop_id, wanted)
        assert quote.total == Decimal("141.00")
    finally:
        conn.close()


# --- DB helpers ---

def test_quote_db_round_trip_and_update_ignores_client_totals(tmp_path):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        quote = build_quote(
            conn, shop_id,
            [WantedLine("tomato", Decimal(2), "kg", "text"),
             WantedLine("coconut", Decimal(1), "piece", "text")])
        token = db.create_quote(conn, shop_id=shop_id, quote=quote)
        assert isinstance(token, str) and len(token) >= 16
        assert token.strip() == token
        row = db.get_quote_by_token(conn, token)
        assert row is not None
        assert row["shop_id"] == shop_id
        assert row["total"] == "51.00"
        assert row["status"] == "new"
        assert db.get_quote_by_token(conn, "nope-not-a-token") is None
        # Client tries to smuggle totals; server recomputes from shop prices.
        updated = db.update_quote_lines(conn, token, [
            {"name_en": "tomato", "qty": "1", "unit": "kg",
             "unit_price": "1", "line_total": "1"},
            {"name_en": "coconut", "qty": "2", "unit": "piece",
             "unit_price": "999", "line_total": "999"},
        ])
        assert updated.total == Decimal("48.00")
        row2 = db.get_quote_by_token(conn, token)
        assert row2["total"] == "48.00"
        lines = json.loads(row2["lines_json"])
        assert [line["line_total"] for line in lines] == ["18.00", "30.00"]
        assert all(line["unit_price"] in ("18", "15") for line in lines)
        # list_quotes for the seller dashboard.
        since = datetime.now(UTC) - timedelta(days=1)
        rows = db.list_quotes(conn, shop_id, since)
        assert [r["token"] for r in rows] == [token]
        other_id, _, _ = make_shop(conn, name="Other Stall")
        assert db.list_quotes(conn, other_id, since) == []
    finally:
        conn.close()


def test_quote_token_unique(tmp_path):
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        quote = build_quote(
            conn, shop_id, [WantedLine("tomato", Decimal(1), "kg", "text")])
        first = db.create_quote(conn, shop_id=shop_id, quote=quote)
        second = db.create_quote(conn, shop_id=shop_id, quote=quote)
        assert first != second
    finally:
        conn.close()


# --- routes ---

def make_client(tmp_path, monkeypatch, **kwargs):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    env.update(kwargs.get("extra_env") or {})
    settings = load_settings(env)
    return TestClient(create_app(settings), follow_redirects=False)


def seed_published(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        return seed_standard(conn)
    finally:
        conn.close()


def test_quote_choice_page_has_three_cards(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    html = client.get(f"/s/{slug}/quote").text
    assert "Get a price quote" in html
    assert "Speak" in html and "Type" in html and "Photo" in html
    assert "style=" not in html


def test_text_quote_post_redirects_to_token(tmp_path, monkeypatch):
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(fake_query_json()))
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    response = client.post(f"/s/{slug}/quote",
                           data={"items": "2 kg tomato, 1 dozen banana"})
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    assert location.startswith("/q/")
    token = location.split("/q/")[1].split("?")[0]
    assert token and not token.isdigit()


def test_quote_page_renders_lines_total_and_whatsapp(tmp_path, monkeypatch):
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(fake_query_json(
            extra=[("dragonfruit", 1, "kg")])))

    def fake_transcribe(wav, **kwargs):
        raise AssertionError("text path must not transcribe")

    monkeypatch.setattr("app.web.quotes.transcribe_wav", fake_transcribe)
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    location = client.post(
        f"/s/{slug}/quote", data={"items": "tomato banana coconut"}).headers[
            "location"]
    html = client.get(location).text
    assert "₹36" in html and "₹60" in html and "₹45" in html
    assert "₹141" in html
    import html as html_lib

    assert "not on this shop's list" in html_lib.unescape(html)
    assert "Prices from" in html and "set " in html
    assert "https://wa.me/914400000001?text=" in html
    assert "%2Fq%2F" in html or "%2Fq" in html or "/q/" in html
    assert f'href="{location}/pdf"' in html
    assert "style=" not in html
    assert "- / +" in html or "−" in html or "stepper" in html


def test_quote_lines_post_recomputes_server_side(tmp_path, monkeypatch):
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(fake_query_json()))
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    location = client.post(
        f"/s/{slug}/quote", data={"items": "tomato"}).headers["location"]
    token = location.split("/q/")[1]
    response = client.post(
        f"/q/{token}/lines",
        data={"qty_0": "1", "qty_1": "1", "qty_2": "1",
              "total": "1", "line_total_0": "1"})
    assert response.status_code in (302, 303)
    html = client.get(location).text
    assert "₹18" in html and "₹60" in html and "₹15" in html
    assert "₹93" in html


def test_quote_pdf_renders(tmp_path, monkeypatch):
    from pypdf import PdfReader

    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(fake_query_json()))
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    location = client.post(
        f"/s/{slug}/quote", data={"items": "tomato"}).headers["location"]
    pdf = client.get(location + "/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"
    text = "\n".join(page.extract_text() or ""
                     for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "₹141" in text
    assert "not priced" in text.lower() or "from" in text.lower()


def test_public_quote_urls_use_tokens_not_ids(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    assert client.get("/q/123").status_code == 404
    assert client.get("/q/123/pdf").status_code == 404
    assert client.get(f"/s/{slug}/quote").status_code == 200


def test_shop_page_has_quote_button_and_market_links_quote(tmp_path,
                                                          monkeypatch):
    from app.market.search import Query, Want

    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    html = client.get(f"/s/{slug}").text
    assert "Get a price quote" in html
    assert f"/s/{slug}/quote" in html
    assert "btn-primary" in html

    def fake_parse_query(text, **kwargs):
        return Query([Want("tomato", None, None, None)], None, None)

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    market = client.get("/market", params={"q": "tomato"}).text
    assert f"/s/{slug}/quote" in market


def test_voice_and_photo_quote_use_background_stages(tmp_path, monkeypatch):
    from app.models import Transcript, Turn

    monkeypatch.setattr("app.web.quotes.jobs.submit",
                        lambda fn, *a: fn(*a))
    monkeypatch.setattr(
        "app.web.quotes.extract_audio",
        lambda src, out: Path(out).write_bytes(b"wav") or Path(out))

    def fake_transcribe(wav, **kwargs):
        return Transcript(text="2 kg tomato", duration_ms=1000,
                          turns=[Turn(1, 0, 1000, "2 kg tomato")])

    from app.market.search import parse_query_json

    monkeypatch.setattr("app.web.quotes.transcribe_wav", fake_transcribe)
    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(fake_query_json(
            tomato=(2, "kg"), banana=None, coconut=None)))
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    response = client.post(
        f"/s/{slug}/quote",
        files={"audio": ("list.webm", b"fake-audio", "audio/webm")})
    assert response.status_code in (302, 303)
    assert "/quote/" in response.headers["location"]
    status_url = response.headers["location"] + "/status"
    payload = client.get(status_url).json()
    assert payload["steps"]
    assert [s["key"] for s in payload["steps"]] == [
        "received", "listening", "matching", "ready"]
    assert payload["quote_token"]


def test_photo_quote_background_stages(tmp_path, monkeypatch):
    from app.pipeline.vision import DetectedProduct, PhotoReport

    monkeypatch.setattr("app.web.quotes.jobs.submit",
                        lambda fn, *a: fn(*a))

    def fake_chat_json(messages, **kwargs):
        return {"kind": "items",
                "products": [{"name_en": "coconut", "countable": True}]}

    def fake_analyse(photo, *, shop_items, ledger, settings):
        return PhotoReport(
            products=[DetectedProduct(name_en="coconut", countable=True,
                                      count=2)],
            quality="good", suggestions=[], cost_usd=0.0)

    monkeypatch.setattr("app.market.quote.chat_json", fake_chat_json)
    monkeypatch.setattr("app.market.quote.analyse_photo", fake_analyse)
    client = make_client(tmp_path, monkeypatch)
    _, slug, _ = seed_published(tmp_path)
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(buf, "JPEG")
    response = client.post(
        f"/s/{slug}/quote",
        files={"photo": ("items.jpg", buf.getvalue(), "image/jpeg")})
    assert response.status_code in (302, 303)
    payload = client.get(response.headers["location"] + "/status").json()
    assert [s["key"] for s in payload["steps"]] == [
        "received", "looking", "matching", "ready"]
    assert payload["quote_token"]


def test_quote_numbers_only_from_shop_list(tmp_path, monkeypatch, ledger,
                                          settings):
    """Property-style: totals derive only from published price lines."""
    import random

    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = seed_standard(conn)
        version_id = db.latest_version(conn, shop_id, published_only=True)
        shop_prices = {
            (line.price, line.per_amount, line.unit)
            for item in db.version_items(conn, version_id)
            for line in item.price_lines if line.price is not None
        }
        shop_price_values = {price for price, _, _ in shop_prices}
        rng = random.Random(27)
        names = ["tomato", "banana", "coconut", "onion", "dragonfruit",
                 "shallot", "potato"]
        units = ["kg", "g", "dozen", "piece", None]
        for _ in range(25):
            wanted = []
            for _ in range(rng.randint(1, 4)):
                name = rng.choice(names)
                qty = (None if rng.random() < 0.3
                       else Decimal(rng.randint(1, 5)))
                unit = rng.choice(units)
                wanted.append(WantedLine(name, qty, unit, "text"))
            quote = build_quote(conn, shop_id, wanted)
            for line in quote.lines:
                if line.unit_price is not None:
                    assert line.unit_price in shop_price_values
                    assert (line.unit_price, line.per_amount,
                            line.unit) in shop_prices or line.unit in (
                                "kg", "g")
                if line.status in ("not_on_list", "sold_out"):
                    assert line.line_total is None
            priced = [line.line_total for line in quote.lines
                      if line.status == "priced"]
            needs = [line.line_total for line in quote.lines
                     if line.status == "needs_qty"]
            assert quote.total == sum(priced + needs, Decimal("0.00"))
    finally:
        conn.close()


def test_quote_stages_registered():
    assert db.stages_for_kind("quote_voice") == [
        "received", "listening", "matching", "ready"]
    assert db.stages_for_kind("quote_photo") == [
        "received", "looking", "matching", "ready"]
    assert db.stage_label("quote_voice", "listening") == "Listening"
    assert db.stage_label("quote_photo", "looking") == "Looking"
