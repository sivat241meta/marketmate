"""Task 55: quantities spoken after the item, banana variety on every bill."""

from __future__ import annotations

import asyncio
import io
import json
from decimal import Decimal
from typing import ClassVar

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Item, PriceLine, Proof


def _proof():
    return Proof(quote="q", turn_ids=[1], start_ms=0, end_ms=1000)


def _item(name_en, variety, price, name_local=""):
    return Item(
        id=0, version_id=0, name_local=name_local or name_en, name_en=name_en,
        variety=variety, qty=None, qty_unit=None, photo=None, sold_out=False,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        proof=_proof(),
    )


def _shop_items():
    return [
        _item("tomato", None, 30, "தக்காளி"),
        _item("onion", None, 40, "வெங்காயம்"),
        _item("ginger", None, 150, "இஞ்சி"),
        _item("garlic", None, 90, "பூண்டு"),
        _item("banana", "poovan", 60, "வாழைப்பழம்"),
        _item("banana", "yelakki", 100, "வாழைப்பழம்"),
    ]


def _seed_shop(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name="Task55 Shop", phone="+914400000001", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken=n, name_local=local, name_en=n, variety=v,
                      price_lines=[PriceLine(Decimal(p), Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof())
            for n, v, p, local in [
                ("tomato", None, 30, "தக்காளி"),
                ("onion", None, 40, "வெங்காயம்"),
                ("ginger", None, 150, "இஞ்சி"),
                ("garlic", None, 90, "பூண்டு"),
                ("banana", "poovan", 60, "வாழைப்பழம்"),
                ("banana", "yelakki", 100, "வாழைப்பழம்"),
            ]
        ])
        db.set_published(conn, version_id, True)
        return shop_id, slug, token
    finally:
        conn.close()


def _seed_bill(tmp_path, shop_id, wanted):
    from app.market.quote import build_quote

    conn = db.connect(tmp_path / "data")
    try:
        quote = build_quote(conn, shop_id, wanted)
        token = db.create_quote(conn, shop_id=shop_id, quote=quote,
                                source="seller", kind="bill", status="billed")
        return db.get_quote_by_token(conn, token)["id"]
    finally:
        conn.close()


# --- 1. quantity after the item ---

def test_qty_after_each_example():
    from app.market.order_parse import parse_order

    items = _shop_items()
    cases = [
        ("தக்காளி ரெண்டு கிலோ", "tomato", None, Decimal(2), "kg"),
        ("tomato 2 kg", "tomato", None, Decimal(2), "kg"),
        ("பூவன் பழம் ரெண்டு கிலோ", "banana", "poovan", Decimal(2), "kg"),
        ("ஏலக்கி அரை கிலோ", "banana", "yelakki", Decimal("0.5"), "kg"),
        ("ரெண்டு கிலோ தக்காளி", "tomato", None, Decimal(2), "kg"),
    ]
    for text, name, variety, qty, unit in cases:
        lines, leftover = parse_order(text, items, "ta")
        assert leftover == [], text
        assert len(lines) == 1, text
        got = lines[0]
        assert (got.name_en, got.variety, got.qty, got.unit) == (
            name, variety, qty, unit), text


def test_qty_after_comma_list():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "வெங்காயம் அரை கிலோ, இஞ்சி கால் கிலோ", _shop_items(), "ta")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("onion", Decimal("0.5"), "kg"),
        ("ginger", Decimal("0.25"), "kg"),
    ]


def test_mixed_before_and_after():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "ரெண்டு கிலோ தக்காளி, வெங்காயம் அரை கிலோ", _shop_items(), "ta")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("tomato", Decimal(2), "kg"),
        ("onion", Decimal("0.5"), "kg"),
    ]


def test_no_separator_item_first_pairs_after():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "tomato 2 kg onion 1 kg", _shop_items(), "en")
    assert leftover == []
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("tomato", Decimal(2), "kg"),
        ("onion", Decimal(1), "kg"),
    ]


def test_amount_before_and_after_item():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order("garlic ₹20 worth", _shop_items(), "en")
    assert leftover == []
    assert len(lines) == 1
    assert lines[0].name_en == "garlic"
    assert lines[0].amount == Decimal(20)
    lines, leftover = parse_order("₹20 worth garlic", _shop_items(), "en")
    assert leftover == []
    assert len(lines) == 1
    assert lines[0].name_en == "garlic"
    assert lines[0].amount == Decimal(20)


def test_unpaired_quantity_needs_spark_and_shows_in_note():
    from app.market.order_parse import (
        item_like_leftovers,
        leftover_needs_spark,
        parse_order,
    )

    lines, leftover = parse_order(
        "தக்காளி ரெண்டு கிலோ ஏழு", _shop_items(), "ta")
    assert [(w.name_en, w.qty, w.unit) for w in lines] == [
        ("tomato", Decimal(2), "kg")]
    assert leftover != []
    assert leftover_needs_spark(leftover) is True
    note = item_like_leftovers(leftover, [w.name_en for w in lines])
    assert any("ஏழு" in word for word in note)


class _FakeOrderRealtime:
    events_to_send: ClassVar = []

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


def test_live_turn_with_unpaired_qty_calls_spark(tmp_path, monkeypatch):
    from app.web.main import create_app

    _, _, token = _seed_shop(tmp_path)

    class _Realtime(_FakeOrderRealtime):
        events_to_send: ClassVar = [
            {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
            {"type": "speechComplete", "turnId": 0,
             "transcript": "தக்காளி ரெண்டு கிலோ ஏழு", "startMs": 0,
             "endMs": 2000},
        ]

    monkeypatch.setattr("app.web.live.RealtimeASR", _Realtime)
    spark_calls = []
    from app.market.search import parse_query_json

    def fake_parse_query(text, **kw):
        spark_calls.append(text)
        return parse_query_json({"wants": [], "budget": None, "area": None})

    monkeypatch.setattr("app.market.quote.parse_query", fake_parse_query)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    client.cookies.set("ui_lang", "en")
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "bill"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 100)
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
    assert done and "bill_url" in done, done
    assert len(spark_calls) == 1
    assert "ஏழு" in spark_calls[0]
    html = client.get(done["bill_url"]).text
    assert "Not understood" in html


# --- 2. banana variety on every bill ---

def test_bill_page_pdf_and_close_show_poovan(tmp_path):
    from pypdf import PdfReader

    from app.market.quote import WantedLine

    shop_id, _, token = _seed_shop(tmp_path)
    bill_id = _seed_bill(
        tmp_path, shop_id,
        [WantedLine("banana", Decimal(2), "kg", "local", variety="poovan")])
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    from app.web.main import create_app

    client = TestClient(create_app(settings))
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Banana (Poovan)" in html
    assert "வாழைப்பழம் (பூவன்)" in html
    pdf = client.get(f"/e/{token}/bills/{bill_id}/pdf")
    assert pdf.status_code == 200
    text = "\n".join(page.extract_text() or ""
                     for page in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Poovan" in text
    close_html = client.get(f"/e/{token}/close").text
    assert "Poovan" in close_html


def test_customer_order_page_shows_poovan(tmp_path):
    from app.market.quote import WantedLine, build_quote

    shop_id, _, _ = _seed_shop(tmp_path)
    conn = db.connect(tmp_path / "data")
    try:
        quote = build_quote(
            conn, shop_id,
            [WantedLine("banana", Decimal(1), "kg", "text",
                        variety="yelakki")])
        token = db.create_quote(conn, shop_id=shop_id, quote=quote)
    finally:
        conn.close()
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    from app.web.main import create_app

    client = TestClient(create_app(settings))
    html = client.get(f"/q/{token}").text
    assert "Banana (Yelakki)" in html


def test_old_bill_row_without_variety_still_renders(tmp_path):
    from app.market.quote import WantedLine

    shop_id, _, token = _seed_shop(tmp_path)
    bill_id = _seed_bill(
        tmp_path, shop_id,
        [WantedLine("banana", Decimal(1), "kg", "local", variety="poovan")])
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT lines_json FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        lines = json.loads(row["lines_json"])
        for line in lines:
            line.pop("variety", None)
        conn.execute("UPDATE quotes SET lines_json = ? WHERE id = ?",
                     (json.dumps(lines), bill_id))
        conn.commit()
    finally:
        conn.close()
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    from app.web.main import create_app

    client = TestClient(create_app(settings))
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Banana" in html
    # The billed line itself is plain; only the add-item select names Poovan.
    assert 'line-name">Banana <span' in html
    close_html = client.get(f"/e/{token}/close").text
    assert "Banana" in close_html
    assert "(Poovan)" not in close_html


def test_bill_edit_and_quote_edit_keep_variety(tmp_path):
    from app.market.quote import WantedLine

    shop_id, _, token = _seed_shop(tmp_path)
    bill_id = _seed_bill(
        tmp_path, shop_id,
        [WantedLine("banana", Decimal(1), "kg", "local", variety="poovan")])
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    from app.web.main import create_app

    client = TestClient(create_app(settings), follow_redirects=False)
    # Old-style edit post without a variety field still keeps poovan.
    response = client.post(
        f"/e/{token}/bills/{bill_id}/lines",
        data={"name_en_0": "banana", "qty_0": "3", "unit_0": "kg"})
    assert response.status_code in (302, 303)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Banana (Poovan)" in html
    assert "₹180" in html
    # Adding a yelakki line from the pricelist select prices yelakki.
    response = client.post(
        f"/e/{token}/bills/{bill_id}/add",
        data={"name_en": "banana (yelakki)", "qty": "1", "unit": "kg"})
    assert response.status_code in (302, 303)
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Banana (Yelakki)" in html
    assert "Banana (Poovan)" in html
    conn = db.connect(tmp_path / "data")
    try:
        quote = db.get_quote_by_id(conn, bill_id)
        stored = json.loads(quote["lines_json"])
        assert [line.get("variety") for line in stored] == [
            "poovan", "yelakki"]
        quote_token = db.create_quote(
            conn, shop_id=shop_id,
            quote=__import__("app.market.quote", fromlist=["build_quote"])
            .build_quote(
                conn, shop_id,
                [WantedLine("banana", Decimal(1), "kg", "text",
                            variety="poovan")]))
        db.update_quote_lines(conn, quote_token, [
            {"name_en": "banana", "qty": "2", "unit": "kg"}])
        row = db.get_quote_by_token(conn, quote_token)
        assert json.loads(row["lines_json"])[0].get("variety") == "poovan"
    finally:
        conn.close()
