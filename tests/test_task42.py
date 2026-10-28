"""Task 42: live billing never drops items, Tamil spelling variants, live limits."""

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


def _review_items():
    """The exact shop list from the reviewer's live test."""
    return [
        _item("small onion", "சின்ன வெங்காயம்", 15, "0.5", "kg"),
        _item("onion", "பெரிய வெங்காயம்", 20, 1, "kg"),
        _item("potato", "உருளைக்கிழங்கு", 5, 1, "kg"),
        _item("ginger", "இஞ்சி", 150, 1, "kg"),
        _item("garlic", "பூண்டு", 90, 1, "kg"),
    ]


REVIEW_TRANSCRIPT = "இரண்டு கிலோ வெங்காயம், அரை கிலோ இஞ்சி, இருபது ரூபாக்கு பூண்டு:"


def _seed_shop(tmp_path, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name="Task42 Shop", phone="+914400000001", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
        return shop_id, slug, token
    finally:
        conn.close()


def _review_drafts():
    return [
        DraftItem(name_spoken=n, name_local=local, name_en=n, variety=None,
                  price_lines=[PriceLine(Decimal(p), Decimal(per), u)],
                  qty=None, qty_unit=None, proof=_proof())
        for n, local, p, per, u in [
            ("small onion", "சின்ன வெங்காயம்", 15, "0.5", "kg"),
            ("onion", "பெரிய வெங்காயம்", 20, 1, "kg"),
            ("potato", "உருளைக்கிழங்கு", 5, 1, "kg"),
            ("ginger", "இஞ்சி", 150, 1, "kg"),
            ("garlic", "பூண்டு", 90, 1, "kg"),
        ]
    ]


# --- 1. the reviewer's transcript ---

def test_reviewer_transcript_bills_all_three(tmp_path):
    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    shop_id, _, _ = _seed_shop(tmp_path, _review_drafts())
    conn = db.connect(tmp_path / "data")
    try:
        items = db.version_items(conn, db.latest_version(
            conn, shop_id, published_only=True))
        lines, leftover = parse_order(REVIEW_TRANSCRIPT, items, "ta")
        assert leftover == [], leftover
        quote = build_quote(conn, shop_id, lines)
        by_name = {line.name_en: line for line in quote.lines}
        assert set(by_name) == {"onion", "ginger", "garlic"}
        assert by_name["onion"].qty == Decimal(2)
        assert by_name["onion"].line_total == Decimal("40.00")
        assert by_name["ginger"].qty == Decimal("0.5")
        assert by_name["ginger"].line_total == Decimal("75.00")
        assert by_name["garlic"].qty == Decimal("0.22")
        assert by_name["garlic"].unit == "kg"
        assert by_name["garlic"].line_total == Decimal("20.00")
        assert quote.total == Decimal("135.00")
    finally:
        conn.close()


def test_full_local_name_still_matches_small_onion():
    from app.market.order_parse import parse_order

    lines, leftover = parse_order(
        "1 கிலோ சின்ன வெங்காயம்", _review_items(), "ta")
    assert leftover == [], leftover
    assert [(w.name_en, w.qty) for w in lines] == [("small onion", Decimal(1))]
    lines, leftover = parse_order(
        "1 கிலோ பெரிய வெங்காயம்", _review_items(), "ta")
    assert leftover == [], leftover
    assert [(w.name_en, w.qty) for w in lines] == [("onion", Decimal(1))]


def test_ambiguous_generic_asks_which_one(tmp_path):
    from app.market.order_parse import parse_order
    from app.market.quote import build_quote

    items = [
        _item("bottle gourd", "சுரைக்காய்", 20, 1, "kg"),
        _item("bitter gourd", "பாகற்காய்", 30, 1, "kg"),
    ]
    lines, _ = parse_order("1 kg gourd", items, "en")
    assert len(lines) == 1
    assert sorted(lines[0].options or []) == ["bitter gourd", "bottle gourd"]
    assert lines[0].qty == Decimal(1)

    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000001", area="A", language="en",
            currency="INR", shop_type="vegetable", listed=True)
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [
            DraftItem(name_spoken=n, name_local=n, name_en=n, variety=None,
                      price_lines=[PriceLine(Decimal(p), Decimal(1), "kg")],
                      qty=None, qty_unit=None, proof=_proof())
            for n, p in [("bottle gourd", 20), ("bitter gourd", 30)]
        ])
        db.set_published(conn, version_id, True)
        quote = build_quote(conn, shop_id, lines)
        assert quote.lines[0].status == "choose"
        assert "Which one" in (quote.lines[0].note or "")
        assert "Bottle gourd" in (quote.lines[0].note or "")
        assert "Bitter gourd" in (quote.lines[0].note or "")
        assert quote.lines[0].line_total is None
    finally:
        conn.close()


def test_single_candidate_needs_no_question():
    from app.market.order_parse import parse_order

    items = [_item("bottle gourd", "சுரைக்காய்", 20, 1, "kg")]
    lines, leftover = parse_order("1 kg gourd", items, "en")
    assert leftover == [], leftover
    assert [(w.name_en, w.qty) for w in lines] == [("bottle gourd", Decimal(1))]


# --- 1b/1c. live finalize: full re-parse, slow fallback, leftover note ---

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


def _recv_until_done(ws):
    from starlette.websockets import WebSocketDisconnect

    done = None
    try:
        while True:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "done":
                done = msg
                break
            if msg["type"] == "error":
                raise AssertionError(f"live error: {msg}")
    except WebSocketDisconnect:
        pass
    return done


def test_live_stop_reparses_full_transcript(tmp_path, monkeypatch):
    from app.web.main import create_app

    _, _, token = _seed_shop(tmp_path, _review_drafts())
    events = [
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
        {"type": "speechComplete", "turnId": 0,
         "transcript": "இரண்டு கிலோ", "startMs": 0, "endMs": 1500},
        {"type": "speechStart", "turnId": 1, "audioProcessedMs": 1600},
        {"type": "speechComplete", "turnId": 1,
         "transcript": "வெங்காயம்", "startMs": 1500, "endMs": 3000},
    ]

    class _Realtime(_FakeOrderRealtime):
        events_to_send: ClassVar = events

    monkeypatch.setattr("app.web.live.RealtimeASR", _Realtime)
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [], "budget": None, "area": None}))
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "bill"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 100)
        ws.send_text(json.dumps({"type": "stop"}))
        done = _recv_until_done(ws)
    assert done and done.get("bill_url", "").startswith(f"/e/{token}/bills/")
    bill_id = done["bill_url"].rsplit("/", 1)[1]
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        assert Decimal(row["total"]) == Decimal("40.00")
    finally:
        conn.close()


def test_live_done_waits_for_slow_fallback(tmp_path, monkeypatch):
    import time

    from app.market.quote import WantedLine
    from app.web.main import create_app

    _, _, token = _seed_shop(tmp_path, _review_drafts())
    events = [
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
        {"type": "speechComplete", "turnId": 0,
         "transcript": "2 kg dragonfruit", "startMs": 0, "endMs": 2000},
    ]

    class _Realtime(_FakeOrderRealtime):
        events_to_send: ClassVar = events

    monkeypatch.setattr("app.web.live.RealtimeASR", _Realtime)

    def slow_wanted(text, **kw):
        time.sleep(2)
        return [WantedLine("dragonfruit", Decimal(2), "kg", "text")]

    monkeypatch.setattr("app.web.live.wanted_from_text", slow_wanted)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "bill"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 100)
        ws.send_text(json.dumps({"type": "stop"}))
        done = _recv_until_done(ws)
    assert done and "bill_url" in done, done
    bill_id = done["bill_url"].rsplit("/", 1)[1]
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT * FROM quotes WHERE id = ?",
                           (bill_id,)).fetchone()
        names = [entry["name_en"]
                 for entry in json.loads(row["lines_json"])]
        assert "dragonfruit" in names
    finally:
        conn.close()


def test_leftover_note_shown_on_bill_and_quote_pages(tmp_path, monkeypatch):
    from app.market.quote import WantedLine, build_quote
    from app.web.main import create_app

    shop_id, _, token = _seed_shop(tmp_path, _review_drafts())
    conn = db.connect(tmp_path / "data")
    try:
        quote = build_quote(
            conn, shop_id, [WantedLine("onion", Decimal(1), "kg", "local")])
        bill_token = db.create_quote(
            conn, shop_id=shop_id, quote=quote, source="seller", kind="bill",
            status="billed", not_understood="dragonfruit")
        bill_id = db.get_quote_by_token(conn, bill_token)["id"]
        page_token = db.create_quote(
            conn, shop_id=shop_id, quote=quote,
            not_understood="dragonfruit")
    finally:
        conn.close()
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    client.cookies.set("ui_lang", "en")
    bill_html = client.get(f"/e/{token}/bills/{bill_id}").text
    assert "Not understood: dragonfruit – add it from the list" in bill_html
    assert "alert-warn" in bill_html
    quote_html = client.get(f"/q/{page_token}").text
    assert "Not understood: dragonfruit – add it from the list" in quote_html


def test_live_bill_stores_leftover_note(tmp_path, monkeypatch):
    from app.web.main import create_app

    _, _, token = _seed_shop(tmp_path, _review_drafts())
    events = [
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
        {"type": "speechComplete", "turnId": 0,
         "transcript": "1 kg onion 2 kg dragonfruit", "startMs": 0,
         "endMs": 2000},
    ]

    class _Realtime(_FakeOrderRealtime):
        events_to_send: ClassVar = events

    monkeypatch.setattr("app.web.live.RealtimeASR", _Realtime)
    from app.market.search import parse_query_json

    monkeypatch.setattr(
        "app.market.quote.parse_query",
        lambda text, **kw: parse_query_json(
            {"wants": [], "budget": None, "area": None}))
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    client.cookies.set("ui_lang", "en")
    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "bill"}))
        assert json.loads(ws.receive_text())["type"] == "ready"
        ws.send_bytes(b"\x00\x01" * 100)
        ws.send_text(json.dumps({"type": "stop"}))
        done = _recv_until_done(ws)
    assert done and "bill_url" in done, done
    html = client.get(done["bill_url"]).text
    assert "Not understood: dragonfruit – add it from the list" in html


# --- 2. Tamil spelling variants ---

def test_tamil_spelling_variants_parse():
    from app.pipeline.numbers import find_numbers, parse_number

    assert parse_number("என்பத்தேழு") == 87
    assert parse_number("எண்பத்தேழு") == 87
    assert parse_number("இருவது") == 20
    assert parse_number("ஐம்பது") == 50
    assert parse_number("அம்பது") == 50
    assert find_numbers("விலை என்பத்தேழு ரூபா") == [(Decimal(87), "tamil")]


def test_misspelled_87_has_no_false_flags():
    from app.pipeline.checks import check_item

    item = DraftItem(
        name_spoken="pomegranate", name_local="மாதுளை",
        name_en="pomegranate", variety=None,
        price_lines=[PriceLine(Decimal(87), Decimal(1), "kg", "kilo 87")],
        qty=None, qty_unit=None,
        proof=_proof_with("இது மாதுளை கிலோ என்பத்தேழு ரூபா"))
    codes = [f.code for f in check_item(item, {})]
    assert "NOT_HEARD" not in codes
    assert "UNCLEAR_NUMBER" not in codes


def _proof_with(quote):
    return Proof(quote=quote, turn_ids=[1], start_ms=0, end_ms=1000)


def test_fifty_eighty_sound_alike_still_fires():
    from app.pipeline.checks import check_item

    for word, price, other in [("எம்பது", 80, 50), ("ஐம்பது", 50, 80)]:
        item = DraftItem(
            name_spoken="ginger", name_local="இஞ்சி", name_en="ginger",
            variety=None,
            price_lines=[PriceLine(Decimal(price), Decimal(1), "kg", "")],
            qty=None, qty_unit=None,
            proof=_proof_with(f"இஞ்சி கிலோ {word} ரூபாய்"))
        flag = next(f for f in check_item(item, {})
                    if f.code == "SOUND_ALIKE")
        assert sorted(flag.options) == [str(min(price, other)),
                                        str(max(price, other))]


# --- 3. live prices 5-minute limit finalizes ---

def test_live_prices_timeout_finalizes_with_message(tmp_path, monkeypatch):
    from decimal import Decimal

    from app.web.main import create_app

    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    resp = client.post("/new", data={
        "name": "Live Shop", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    token = resp.headers["location"].split("/e/")[1]

    events = [
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 100},
        {"type": "speechComplete", "turnId": 0,
         "transcript": "தக்காளி கிலோ இருபது ரூபா",
         "startMs": 0, "endMs": 2000},
    ]

    class _Realtime(_FakeOrderRealtime):
        events_to_send: ClassVar = events

    monkeypatch.setattr("app.web.live.RealtimeASR", _Realtime)

    def fake_extract(transcript, *, ledger, settings, language="ta",
                     progress=None):
        return [DraftItem(
            name_spoken="thakkali", name_local="தக்காளி", name_en="tomato",
            variety=None,
            price_lines=[PriceLine(Decimal(20), Decimal(1), "kg",
                                   "kilo irupathu")],
            qty=None, qty_unit=None,
            proof=Proof(quote="தக்காளி கிலோ இருபது ரூபா", turn_ids=[1],
                        start_ms=0, end_ms=2000))]

    monkeypatch.setattr("app.web.live.extract_items", fake_extract)
    monkeypatch.setattr("app.pipeline.run.extract_items", fake_extract)

    from pathlib import Path

    def fake_make_photo(frame, noun, out, *, ledger, settings):
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"fakejpeg")
        return Path(out)

    monkeypatch.setattr("app.pipeline.run.make_photo", fake_make_photo)

    clock = {"t": 1000.0}
    monkeypatch.setattr("app.web.live.monotonic", lambda: clock["t"])

    with client.websocket_connect(f"/e/{token}/live/ws") as ws:
        ws.send_text(json.dumps({"type": "start", "kind": "prices"}))
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        session_id = ready["session_id"]
        ws.send_bytes(b"\x00\x01" * 2400)
        # Wait for the turn, then jump past the 5-minute limit.
        from starlette.websockets import WebSocketDisconnect

        done = None
        try:
            while True:
                msg = json.loads(ws.receive_text())
                if msg["type"] == "turn":
                    clock["t"] = 1000.0 + 301.0
                elif msg["type"] == "done":
                    done = msg
                    break
                elif msg["type"] == "error":
                    raise AssertionError(f"relay error: {msg}")
        except WebSocketDisconnect:
            pass
        assert done and done.get("review_url", "").endswith(
            f"/e/{token}/s/{session_id}")
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT status, message FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        assert row["status"] == "review"
        assert row["message"] == "Stopped at 5 minutes – check what we heard"
        assert len(db.load_drafts(conn, session_id)) == 1
    finally:
        conn.close()
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "Stopped at 5 minutes – check what we heard" in html


# --- 4. live page polish ---

def test_live_page_ready_and_finishing_states(tmp_path):
    from app.web.main import create_app

    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    resp = client.post("/new", data={
        "name": "Live Shop", "phone": "+914400000000", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    token = resp.headers["location"].split("/e/")[1]
    html = client.get(f"/e/{token}/live").text
    assert "Ready" in html
    assert "Finishing – checking every price…" in html
    assert "data-live-timer" in html
    assert "data-live-elapsed" in html
    # Task 52: the pill shows the language name and the timer always.
    timer_tag = next(line for line in html.splitlines()
                     if "data-live-timer" in line)
    assert "0:00" in timer_tag
    assert "hidden" not in timer_tag
    assert "தமிழ்" in html
