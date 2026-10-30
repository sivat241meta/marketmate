"""Task 36: live voice billing, local order parser, amount orders, quick weights."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import ClassVar

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Item, PriceLine, Proof


def _proof():
    return Proof(quote="q", turn_ids=[1], start_ms=0, end_ms=1000)


def _item(name_en, name_local, price, per_amount=1, unit="kg"):
    return Item(
        id=0, version_id=0, name_local=name_local, name_en=name_en,
        variety=None, qty=None, qty_unit=None, photo=None, sold_out=False,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        proof=_proof(),
    )


def _std_items():
    return [
        _item("onion", "பெரிய வெங்காயம்", 30, 1, "kg"),
        _item("ginger", "இஞ்சி", 100, 1, "kg"),
        _item("coriander", "கொத்தமல்லி", 10, 1, "bunch"),
        _item("tomato", "தக்காளி", 40, 1, "kg"),
        _item("coconut", "தேங்காய்", 15, 1, "piece"),
        _item("banana", "வாழைப்பழம்", 60, 1, "dozen"),
    ]


def _hi_items():
    return [
        _item("onion", "प्याज़", 30, 1, "kg"),
        _item("ginger", "अदरक", 100, 1, "kg"),
    ]


# --- 1. parser cases ---

def test_parse_en_two_items():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order("2 kg onion half kg ginger", _std_items(), "en")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("onion", Decimal(2), "kg"),
        ("ginger", Decimal("0.5"), "kg"),
    ]


def test_parse_ta_two_items():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "ரெண்டு கிலோ வெங்காயம் அரை கிலோ இஞ்சி", _std_items(), "ta")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("onion", Decimal(2), "kg"),
        ("ginger", Decimal("0.5"), "kg"),
    ]


def test_parse_hi_two_items():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "दो किलो प्याज़ आधा किलो अदरक", _hi_items(), "hi")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("onion", Decimal(2), "kg"),
        ("ginger", Decimal("0.5"), "kg"),
    ]


def test_parse_amount_bunch(tmp_path):
    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000001", area="A", language="ta",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken="coriander", name_local="கொத்தமல்லி",
                      name_en="coriander", variety=None,
                      price_lines=[PriceLine(Decimal(10), Decimal(1), "bunch")],
                      qty=None, qty_unit=None, proof=_proof()),
        ])
        db.set_published(conn, version_id, True)
        items = db.version_items(conn, version_id)
        lines, leftover = parse_order("20 rupees coriander", items, "en")
        assert leftover == []
        assert len(lines) == 1 and lines[0].amount == Decimal(20)
        quote = build_quote(conn, shop_id, lines)
        assert quote.lines[0].qty == Decimal(2)
        assert quote.lines[0].unit == "bunch"
        assert quote.lines[0].line_total == Decimal("20.00")
    finally:
        conn.close()


def test_parse_amount_kg(tmp_path):
    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000001", area="A", language="ta",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken="tomato", name_local="தக்காளி",
                      name_en="tomato", variety=None,
                      price_lines=[PriceLine(Decimal(40), Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof()),
        ])
        db.set_published(conn, version_id, True)
        items = db.version_items(conn, version_id)
        lines, leftover = parse_order("₹30 worth tomato", items, "en")
        assert leftover == []
        assert lines[0].amount == Decimal(30)
        quote = build_quote(conn, shop_id, lines)
        assert quote.lines[0].qty == Decimal("0.75")
        assert quote.lines[0].line_total == Decimal("30.00")
        assert "₹30 worth" in (quote.lines[0].note or "")
        assert "0.75 kg" in (quote.lines[0].note or "")
    finally:
        conn.close()


def test_parse_amount_ta():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "இருபது ரூபாய்க்கு கொத்தமல்லி", _std_items(), "ta")
    assert leftover == []
    assert len(lines) == 1
    assert lines[0].name_en == "coriander"
    assert lines[0].amount == Decimal(20)


def test_parse_bare_piece():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order("3 coconut", _std_items(), "en")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("coconut", Decimal(3), "piece")]


def test_parse_unknown_is_leftover():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order("2 kg dragonfruit", _std_items(), "en")
    assert lines == []
    assert any("dragonfruit" in w.lower() for w in leftover)


def test_parse_filler_ignored():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "2 kg onion and also உம் भी அப்புறம்", _std_items(), "en")
    assert [(w.name_en, w.qty) for w in lines] == [("onion", Decimal(2))]
    assert leftover == []


def test_parse_item_without_number_gets_one():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order("tomato", _std_items(), "en")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("tomato", Decimal(1), "kg")]


def test_parse_tamil_suffixes():
    from app.market.order_parse import parse_order

    lines, _ = parse_order("2 kg தக்காளிக்கு", _std_items(), "ta")
    assert [(w.name_en, w.qty) for w in lines] == [("tomato", Decimal(2))]
    lines, _ = parse_order("வெங்காயம்-ம் 2 kg", _std_items(), "ta")
    assert any(w.name_en == "onion" for w in lines)


def test_parse_fractions():
    from app.market.order_parse import parse_order

    cases = [
        ("half kg tomato", Decimal("0.5")),
        ("அரை கிலோ தக்காளி", Decimal("0.5")),
        ("ஒன்றரை கிலோ தக்காளி", Decimal("1.5")),
        ("கால் கிலோ தக்காளி", Decimal("0.25")),
        ("முக்கால் கிலோ தக்காளி", Decimal("0.75")),
    ]
    for text, qty in cases:
        lines, leftover = parse_order(text, _std_items(), "ta")
        assert leftover == [], text
        assert len(lines) == 1 and lines[0].qty == qty, text
    hi_items = [_item("tomato", "टमाटर", 40, 1, "kg")]
    for text, qty in [
        ("आधा किलो टमाटर", Decimal("0.5")),
        ("डेढ़ किलो टमाटर", Decimal("1.5")),
        ("पाव किलो टमाटर", Decimal("0.25")),
        ("पौना किलो टमाटर", Decimal("0.75")),
    ]:
        lines, leftover = parse_order(text, hi_items, "hi")
        assert leftover == [], text
        assert len(lines) == 1 and lines[0].qty == qty, text


def test_parse_rate_only_from_published_list(tmp_path):
    import random

    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000001", area="A", language="ta",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken=n, name_local=n, name_en=n, variety=None,
                      price_lines=[PriceLine(Decimal(p), Decimal(1), u)],
                      qty=None, qty_unit=None, proof=_proof())
            for n, p, u in [("tomato", 18, "kg"), ("banana", 60, "dozen"),
                            ("coconut", 15, "piece"),
                            ("coriander", 10, "bunch")]
        ])
        db.set_published(conn, version_id, True)
        shop_values = {Decimal(18), Decimal(60), Decimal(15), Decimal(10)}
        rng = random.Random(36)
        names = ["tomato", "banana", "coconut", "coriander", "dragonfruit",
                 "onion", "thakkali", "kothamalli"]
        qtys = ["1", "2", "half", "அரை", "दो", "3", "20 rupees", "₹30 worth"]
        units = ["kg", "g", "dozen", "piece", "bunch", ""]
        for _ in range(30):
            bits = []
            for _ in range(rng.randint(1, 3)):
                bits.append(f"{rng.choice(qtys)} {rng.choice(units)}"
                            f" {rng.choice(names)}".strip())
            text = ", ".join(bits)
            items = db.version_items(conn, version_id)
            lines, _ = parse_order(text, items, "en")
            quote = build_quote(conn, shop_id, lines)
            for line in quote.lines:
                if line.unit_price is not None:
                    assert line.unit_price in shop_values
                if line.status in ("not_on_list", "sold_out"):
                    assert line.line_total is None
    finally:
        conn.close()


# --- 2/3. live relays ---

def _seed_shop(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name="Live Bill Shop", phone="+914400000001", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken="tomato", name_local="தக்காளி",
                      name_en="tomato", variety=None,
                      price_lines=[PriceLine(Decimal(40), Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof()),
            DraftItem(name_spoken="onion", name_local="பெரிய வெங்காயம்",
                      name_en="onion", variety=None,
                      price_lines=[PriceLine(Decimal(30), Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof()),
            DraftItem(name_spoken="ginger", name_local="இஞ்சி",
                      name_en="ginger", variety=None,
                      price_lines=[PriceLine(Decimal(100), Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof()),
            DraftItem(name_spoken="coriander", name_local="கொத்தமல்லி",
                      name_en="coriander", variety=None,
                      price_lines=[PriceLine(Decimal(10), Decimal(1), "bunch")],
                      qty=None, qty_unit=None, proof=_proof()),
            DraftItem(name_spoken="coconut", name_local="தேங்காய்",
                      name_en="coconut", variety=None,
                      price_lines=[PriceLine(Decimal(15), Decimal(1), "piece")],
                      qty=None, qty_unit=None, proof=_proof()),
            DraftItem(name_spoken="banana", name_local="வாழைப்பழம்",
                      name_en="banana", variety=None,
                      price_lines=[PriceLine(Decimal(60), Decimal(1), "dozen")],
                      qty=None, qty_unit=None, proof=_proof()),
        ])
        db.set_published(conn, version_id, True)
        return shop_id, slug, token
    finally:
        conn.close()


class _FakeBillRealtime:
    events_to_send: ClassVar = [
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
        {"type": "transcript", "transcript": "2 kg onion"},
        {"type": "speechComplete", "turnId": 0, "transcript": "2 kg onion",
         "startMs": 0, "endMs": 2000},
        {"type": "speechStart", "turnId": 1, "audioProcessedMs": 2100},
        {"type": "speechComplete", "turnId": 1,
         "transcript": "half kg ginger", "startMs": 2000, "endMs": 4000},
    ]

    def __init__(self, *a, **k):
        pass

    async def start(self):
        return "fake"

    async def send_audio(self, data):
        pass

    async def end(self):
        pass

    async def events(self):
        for ev in self.events_to_send:
            await asyncio.sleep(0.005)
            yield dict(ev)

    async def close(self):
        pass


def test_live_bill_relay_lines_and_done(tmp_path, monkeypatch):
    from app.web.main import create_app

    _, _, token = _seed_shop(tmp_path)
    monkeypatch.setattr("app.web.live.RealtimeASR", _FakeBillRealtime)
    spark_calls = []
    from app.market.search import parse_query_json

    def fake_parse_query(text, **kw):
        spark_calls.append(text)
        return parse_query_json({"wants": [], "budget": None, "area": None})

    monkeypatch.setattr("app.market.quote.parse_query", fake_parse_query)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "bill"}))
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 2400)
        seen_lines = []
        ws.send_text(json.dumps({"type": "stop"}))
        from starlette.websockets import WebSocketDisconnect

        done = None
        try:
            while True:
                msg = json.loads(ws.receive_text())
                if msg["type"] == "bill_lines":
                    seen_lines.append(msg)
                elif msg["type"] == "done":
                    done = msg
                    break
        except WebSocketDisconnect:
            pass
        assert len(seen_lines) >= 2, seen_lines
        assert any("onion" in json.dumps(m).lower() for m in seen_lines)
        assert done and done.get("bill_url", "").startswith(
            f"/e/{token}/bills/")
        # Local parser handled clean turns: no Spark fallback.
        assert spark_calls == []
    bill_id = done["bill_url"].rsplit("/", 1)[1]
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        assert row["source"] == "seller"
        assert row["kind"] == "bill"
        assert row["status"] == "billed"
        assert Decimal(row["total"]) == Decimal("110.00")
    finally:
        conn.close()


def test_live_bill_spark_only_for_item_like_leftovers(tmp_path, monkeypatch):
    from app.web.main import create_app

    _, _, token = _seed_shop(tmp_path)

    class _RealtimeUnknown(_FakeBillRealtime):
        events_to_send: ClassVar = [
            {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
            {"type": "speechComplete", "turnId": 0,
             "transcript": "2 kg onion and also", "startMs": 0,
             "endMs": 2000},
            {"type": "speechStart", "turnId": 1, "audioProcessedMs": 2100},
            {"type": "speechComplete", "turnId": 1,
             "transcript": "2 kg dragonfruit", "startMs": 2000,
             "endMs": 4000},
        ]

    monkeypatch.setattr("app.web.live.RealtimeASR", _RealtimeUnknown)
    spark_calls = []
    from app.market.search import parse_query_json

    def fake_parse_query(text, **kw):
        spark_calls.append(text)
        if "dragonfruit" in text:
            return parse_query_json({"wants": [
                {"name": "dragonfruit", "amount": 2, "unit": "kg",
                 "max_rate": None}], "budget": None, "area": None})
        return parse_query_json({"wants": [], "budget": None, "area": None})

    monkeypatch.setattr("app.market.quote.parse_query", fake_parse_query)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "bill"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 100)
        ws.send_text(json.dumps({"type": "stop"}))
        from starlette.websockets import WebSocketDisconnect

        try:
            while True:
                msg = json.loads(ws.receive_text())
                if msg["type"] == "done":
                    break
        except WebSocketDisconnect:
            pass
    assert len(spark_calls) == 1
    assert "dragonfruit" in spark_calls[0]


def test_live_quote_respects_limiter(tmp_path):
    from app.web.main import create_app

    _, slug, _ = _seed_shop(tmp_path)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data"),
                              "UPLOADS_PER_IP_HOUR": "1",
                              "UPLOADS_PER_HOUR": "1"})
    client = TestClient(create_app(settings))
    with client.websocket_connect(f"/s/{slug}/quote/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "quote"}))
        first = json.loads(ws.receive_text())
        assert first["type"] == "ready"
    with client.websocket_connect(f"/s/{slug}/quote/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "quote"}))
        second = json.loads(ws.receive_text())
        assert second["type"] == "error"


def test_live_quote_happy_path_ends_on_quote(tmp_path, monkeypatch):
    from app.web.main import create_app

    _, slug, _ = _seed_shop(tmp_path)
    monkeypatch.setattr("app.web.live.RealtimeASR", _FakeBillRealtime)
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [], "budget": None, "area": None}))
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    with client.websocket_connect(f"/s/{slug}/quote/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "quote"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 2400)
        ws.send_text(json.dumps({"type": "stop"}))
        from starlette.websockets import WebSocketDisconnect

        done = None
        try:
            while True:
                msg = json.loads(ws.receive_text())
                if msg["type"] == "done":
                    done = msg
                    break
        except WebSocketDisconnect:
            pass
        assert done and done.get("quote_url", "").startswith("/q/")
    html = client.get(done["quote_url"]).text
    assert "₹110" in html or "110" in html


# --- 4. quick chips + keypad ---

def _client_with_shop(tmp_path):
    from app.web.main import create_app

    shop_id, slug, token = _seed_shop(tmp_path)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    return client, shop_id, slug, token


def test_quick_chips_and_keypad_render(tmp_path):
    client, shop_id, _, token = _client_with_shop(tmp_path)
    html = client.get(f"/e/{token}/bills/new").text
    for needle in ["100 g", "250 g", "½ kg", "1 kg", "2 kg", "+1", "+6",
                   "+12", "₹", "keypad"]:
        assert needle in html, needle
    assert "amount_0" in html
    # Bill page chips.
    from app.market.quote import WantedLine, build_quote

    conn = db.connect(tmp_path / "data")
    try:
        quote = build_quote(conn, shop_id,
                            [WantedLine("tomato", Decimal(1), "kg", "tap"),
                             WantedLine("coconut", Decimal(2), "piece",
                                        "tap")])
        quote_token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                      source="seller", kind="bill",
                                      status="billed")
        bill_id = db.get_quote_by_token(conn, quote_token)["id"]
    finally:
        conn.close()
    bill_html = client.get(f"/e/{token}/bills/{bill_id}").text
    for needle in ["100 g", "250 g", "½ kg", "+1", "₹", "keypad"]:
        assert needle in bill_html, needle


def test_amount_chip_posts_to_existing_endpoints(tmp_path):
    client, _, _, token = _client_with_shop(tmp_path)
    # Tap form posts amount_N; server converts with the published rate.
    response = client.post(
        f"/e/{token}/bills/new",
        data={"name_en_2": "coriander", "qty_2": "0", "unit_2": "bunch",
              "amount_2": "20"})
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    html = client.get(location).text
    assert "₹20" in html
    assert "worth" in html
    conn = db.connect(tmp_path / "data")
    try:
        bill_id = int(location.rsplit("/", 1)[1])
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        assert row["total"] == "20.00"
    finally:
        conn.close()


def test_live_bill_page_has_speak_live_and_fallback(tmp_path):
    # Task 125: the composer is the only recorder on the page — the
    # old live-order mic block is gone.
    client, _, _, token = _client_with_shop(tmp_path)
    html = client.get(f"/e/{token}/bills/new").text
    assert "data-live-order" not in html
    assert "live-order.js" not in html
    assert "mic-btn" not in html
    assert "data-composer" in html
    assert "composer.js" in html
    assert 'name="audio"' in html
    assert "Upload and bill" not in html
    assert "style=" not in html


def test_quote_speak_has_live_and_fallback(tmp_path):
    # Task 125: the composer is the only recorder on the page — the
    # old live-order mic block is gone.
    client, _, slug, _ = _client_with_shop(tmp_path)
    html = client.get(f"/s/{slug}/quote").text
    assert "data-live-order" not in html
    assert "live-order.js" not in html
    assert "mic-btn" not in html
    assert "data-composer" in html
    assert "composer.js" in html
    assert "Upload" in html or "upload" in html
    assert "style=" not in html
