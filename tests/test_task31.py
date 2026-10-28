"""Task 31: fixes from the owner's live browser check of Tasks 22-30."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof
from app.pipeline.names import CANONICAL_NAMES
from app.web.main import create_app


def _settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})


def _client(tmp_path):
    client = TestClient(create_app(_settings(tmp_path)), follow_redirects=False)
    # Task 40: seller UI defaults to the shop language; these tests pin English.
    client.cookies.set("ui_lang", "en")
    return client


def _seed_shop(tmp_path, name="T31 Store", currency="INR", listed=False,
               language="ta", items=(("tomato", 18, 1, "kg"),)):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, token = db.create_shop(
            conn, name=name, phone="+914400000000", area="Koyambedu",
            language=language, currency=currency, shop_type="vegetable",
            listed=listed)
        if items:
            drafts = [
                DraftItem(
                    name_spoken=n, name_local=CANONICAL_NAMES[n], name_en=n,
                    variety=None,
                    price_lines=[PriceLine(Decimal(p), Decimal(a), u)],
                    qty=None, qty_unit=None,
                    proof=Proof(quote=f"{n} {p}", turn_ids=[1],
                                start_ms=0, end_ms=1000),
                )
                for n, p, a, u in items
            ]
            session_id = db.create_session(conn, shop_id, "video")
            version_id = db.approve(conn, session_id, drafts)
            db.set_published(conn, version_id, True)
        return slug, token, shop_id
    finally:
        conn.close()


def _draft(name_en, price, options=None):
    flags = []
    if options:
        flags.append(Flag(field="price", code="SOUND_ALIKE",
                          message=f"did you say {' or '.join(options)}?",
                          options=list(options)))
    return DraftItem(
        name_spoken=name_en, name_local=CANONICAL_NAMES[name_en],
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[1],
                    start_ms=0, end_ms=1000),
        flags=flags,
    )


def _review_session(tmp_path, shop_id, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        session_id = db.create_session(conn, shop_id, "video")
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review", "needs review")
        return session_id
    finally:
        conn.close()


def _opt_buttons(html):
    return re.findall(r"<button[^>]*class=\"[^\"]*opt-btn[^\"]*\"[^>]*>", html)


# --- 1. SQLite thread safety ---

def test_db_connection_usable_across_threads(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            row = pool.submit(
                lambda: conn.execute("SELECT 1").fetchone()).result()
        assert row[0] == 1
    finally:
        conn.close()


def test_concurrent_page_loads_all_200(tmp_path):
    slug, token, _ = _seed_shop(tmp_path)
    client = _client(tmp_path)
    urls = [f"/s/{slug}", f"/e/{token}", f"/e/{token}/bills"] * 8
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda url: client.get(url).status_code, urls))
    assert codes == [200] * 24


# --- 2. option buttons must not carry data-field ---

def test_review_opt_buttons_use_target_field(tmp_path):
    _slug, token, shop_id = _seed_shop(tmp_path, items=())
    session_id = _review_session(
        tmp_path, shop_id, [_draft("tomato", 180, ["150", "180"])])
    html = _client(tmp_path).get(f"/e/{token}/s/{session_id}").text
    buttons = _opt_buttons(html)
    assert len(buttons) == 2
    for tag in buttons:
        assert "data-field" not in tag
        assert "data-target-field=\"price\"" in tag


def test_update_opt_buttons_use_target_field(tmp_path, monkeypatch):
    from app.models import Transcript, Turn

    _slug, token, _shop_id = _seed_shop(
        tmp_path, items=(("tomato", 18, 1, "kg"), ("onion", 25, 1, "kg")))
    canned = {"changes": [{
        "name_en": "tomato", "action": "set_price",
        "prices": [{"said": "18", "price": 18, "per_amount": 1, "unit": "kg"},
                   {"said": "80", "price": 80, "per_amount": 1, "unit": "kg"}],
        "qty": None, "qty_unit": None, "turn_ids": [1],
        "quote": "tomato 18 no 80"}]}

    def fake_extract_audio(video, out_wav):
        Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
        Path(out_wav).write_bytes(b"RIFF-fake-wav")
        return Path(out_wav)

    def fake_transcribe(wav, **kwargs):
        return Transcript(
            text="tomato 18 no 80", duration_ms=3000,
            turns=[Turn(id=1, start_ms=0, end_ms=3000,
                        text="tomato 18 no 80")])

    monkeypatch.setattr("app.web.seller.extract_audio", fake_extract_audio)
    monkeypatch.setattr("app.web.seller.transcribe_wav", fake_transcribe)
    monkeypatch.setattr("app.pipeline.update.chat_json",
                        lambda messages, **kw: canned)
    posted = _client(tmp_path).post(
        f"/e/{token}/update",
        files={"audio": ("update.webm", b"fake-opus", "audio/webm")})
    assert posted.status_code == 200
    buttons = _opt_buttons(posted.text)
    assert buttons, "two-price update must render option buttons"
    for tag in buttons:
        assert "data-field" not in tag
        assert "data-target-field=" in tag


def test_review_js_queries_inputs_only_and_dispatches_input(tmp_path):
    js = Path("app/web/static/review.js").read_text(encoding="utf-8")
    bare = re.findall(
        r"(?<![A-Za-z0-9_\-\]])\[data-item[^\]]*\]\[data-field", js)
    assert bare == []
    assert "targetField" in js
    assert "input[data-item=" in js and "select[data-item=" in js
    assert "input[data-field=" in js and "select[data-field=" in js
    assert re.search(r"dispatchEvent\(new Event\(\"input\"", js)


# --- 3. review counts count cards ---

def test_review_js_counts_cards_everywhere():
    # Task 45: the card-count wording lives in i18n and reaches review.js
    # through translated data-msg-* attributes on the form.
    js = Path("app/web/static/review.js").read_text(encoding="utf-8")
    assert "msgNeedOne" in js and "msgNeedMany" in js
    assert "flag(s) still need" not in js
    from app.web.i18n import t_for

    assert (t_for("en")("review.need_one")
            == "1 item still needs your choice or a tick")
    assert (t_for("en")("review.need_many", n=2)
            == "2 items still need your choice or a tick")


def test_review_error_hidden_until_approve_pressed():
    js = Path("app/web/static/review.js").read_text(encoding="utf-8")
    assert "approveAttempted" in js


def test_approve_error_message_counts_cards(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name="S", phone="+914400000000", area="A", language="ta",
            currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")
        one = _draft("tomato", 18)
        one.flags.append(Flag(field="price", code="X", message="check tomato"))
        try:
            db.approve(conn, session_id, [one])
            raise AssertionError("expected ApprovalError")
        except db.ApprovalError as exc:
            assert "1 item still needs your choice or a tick" in str(exc)
            assert "Please check tomato:" in str(exc)
        two = _draft("onion", 25)
        two.flags.append(Flag(field="price", code="X", message="check onion"))
        try:
            db.approve(conn, session_id, [one, two])
            raise AssertionError("expected ApprovalError")
        except db.ApprovalError as exc:
            assert "2 items still need your choice or a tick" in str(exc)
    finally:
        conn.close()


# --- 4. sticky bar legibility ---

def test_sticky_bar_has_solid_background_and_page_padding():
    css = Path("app/web/static/app.css").read_text(encoding="utf-8")
    block = re.search(r"\.sticky-bar\s*\{([^}]*)\}", css)
    assert block, "missing .sticky-bar rule"
    body = block.group(1)
    assert "linear-gradient" not in body
    assert re.search(r"background:\s*var\(--cream\)", body)
    assert re.search(r"border-top:\s*1px solid var\(--line\)", body)
    assert "box-shadow" in body
    assert "padding-bottom" in css.split(".sticky-bar", 1)[1][:900]


# --- 5. retry runs in the background ---

def _seed_failed_video(tmp_path):
    _slug, token, shop_id = _seed_shop(tmp_path, items=())
    conn = db.connect(tmp_path / "data")
    try:
        session_id = db.create_session(conn, shop_id, "video")
        db.set_session_status(conn, session_id, "failed", "old failure")
    finally:
        conn.close()
    session_dir = tmp_path / "data" / "sessions" / str(session_id)
    (session_dir / "frames").mkdir(parents=True, exist_ok=True)
    (session_dir / "transcript.json").write_text(json.dumps({
        "text": "tomato 18", "duration_ms": 2000,
        "turns": [{"id": 1, "start_ms": 0, "end_ms": 2000,
                   "text": "tomato 18"}]}))
    (session_dir / "audio.wav").write_bytes(b"fake-wav")
    return token, session_id


def test_video_retry_schedules_background_job(tmp_path, monkeypatch):
    token, session_id = _seed_failed_video(tmp_path)
    calls = []
    monkeypatch.setattr("app.web.seller.jobs.submit",
                        lambda fn, *a: calls.append((fn, a)))

    def explode(*args, **kwargs):
        raise AssertionError("retry must not run synchronously")

    monkeypatch.setattr("app.web.seller.reprocess", explode)
    response = _client(tmp_path).post(f"/e/{token}/s/{session_id}/retry")
    assert response.status_code == 303
    assert response.headers["location"] == f"/e/{token}/s/{session_id}"
    assert len(calls) == 1
    conn = db.connect(tmp_path / "data")
    try:
        row = conn.execute("SELECT status FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        assert row["status"] == "processing"
    finally:
        conn.close()


def test_photo_retry_schedules_background_job(tmp_path, monkeypatch):
    from PIL import Image

    _slug, token, shop_id = _seed_shop(tmp_path, items=())
    conn = db.connect(tmp_path / "data")
    try:
        session_id = db.create_session(conn, shop_id, "photo")
        db.set_session_status(conn, session_id, "failed", "old failure")
    finally:
        conn.close()
    photo_dir = tmp_path / "data" / "photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    image = photo_dir / "retry.jpg"
    Image.new("RGB", (32, 32), "red").save(image, "JPEG")
    meta_dir = tmp_path / "data" / "sessions" / str(session_id)
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "photo.json").write_text(json.dumps(
        {"image": str(image), "check_id": None}))
    calls = []
    monkeypatch.setattr("app.web.seller.jobs.submit",
                        lambda fn, *a: calls.append((fn, a)))

    def explode(*args, **kwargs):
        raise AssertionError("retry must not run synchronously")

    monkeypatch.setattr("app.web.photos.process_photo_session", explode)
    response = _client(tmp_path).post(f"/e/{token}/s/{session_id}/retry")
    assert response.status_code == 303
    assert response.headers["location"] == f"/e/{token}/s/{session_id}"
    assert len(calls) == 1
    assert calls[0][0].__name__ == "run_photo_job"


# --- 6. icon sizes ---

def _page_svgs(html):
    tags = re.findall(r"<svg\b([^>]*)>", html)
    return [tag for tag in tags if "boxes" not in tag]


def test_icon_svgs_have_class_and_size(tmp_path):
    slug, token, _ = _seed_shop(tmp_path)
    client = _client(tmp_path)
    pages = {
        "seller": f"/e/{token}",
        "shop": f"/s/{slug}",
        "quote start": f"/s/{slug}/quote",
        "bills new": f"/e/{token}/bills/new",
        "photos": f"/e/{token}/photos",
    }
    for name, url in pages.items():
        html = client.get(url).text
        tags = _page_svgs(html)
        assert tags, f"{name} page should render icons"
        for tag in tags:
            assert re.search(r"class=\"[^\"]*\bicon\b", tag), \
                f"{name}: svg without icon class: <svg{tag}>"
            assert 'width="20"' in tag and 'height="20"' in tag, \
                f"{name}: svg without size: <svg{tag}>"


def test_icon_css_sizes():
    css = Path("app/web/static/app.css").read_text(encoding="utf-8")
    assert re.search(r"\.icon\s*\{[^}]*width:\s*1\.25em", css)
    assert re.search(r"\.mic-btn\s+\.icon\s*\{[^}]*28px", css)
    assert re.search(r"\.empty-state\s+\.icon\s*\{[^}]*40px", css)


# --- 7. money formatting ---

def test_format_money_symbols_and_decimals():
    from app.outputs.money import format_money

    cases = [("INR", "₹"), ("EUR", "€"), ("JPY", "¥"), ("CNY", "¥"),
             ("KRW", "₩"), ("THB", "฿"), ("PHP", "₱"), ("VND", "₫"),
             ("ILS", "₪"), ("TRY", "₺"), ("BRL", "R$"), ("MYR", "RM"),
             ("IDR", "Rp")]
    for code, symbol in cases:
        assert format_money("25", code) == f"{symbol}25", code
    assert format_money("25", "PLN") == "zl25"
    assert format_money("25", "AED") == "AED 25"
    assert format_money(Decimal(18), "INR") == "₹18"
    assert format_money(Decimal("18.50"), "INR") == "₹18.50"
    assert format_money(Decimal("18.5"), "INR") == "₹18.50"
    assert "₹" in format_money(18, "INR")


def test_format_money_indian_grouping():
    from app.outputs.money import format_money

    assert format_money("999", "INR") == "₹999"
    assert format_money("1000", "INR") == "₹1,000"
    assert format_money("125000", "INR") == "₹1,25,000"
    assert format_money("10000000", "INR") == "₹1,00,00,000"
    assert format_money("1000000", "EUR") == "€1,000,000"


def test_new_bill_page_shows_rupee_sign(tmp_path):
    _, token, _ = _seed_shop(tmp_path)
    html = _client(tmp_path).get(f"/e/{token}/bills/new").text
    assert "₹" in html
    assert "Rs." not in html


def test_review_options_use_shop_currency(tmp_path):
    _, token, shop_id = _seed_shop(tmp_path, currency="EUR", language="fr",
                                   items=())
    session_id = _review_session(
        tmp_path, shop_id, [_draft("tomato", 18, ["18", "80"])])
    html = _client(tmp_path).get(f"/e/{token}/s/{session_id}").text
    assert "€18" in html and "€80" in html
    assert "₹18" not in html and "₹80" not in html


# --- 8. photo counts ---

def test_reconcile_zero_uses_nonzero_count():
    from app.pipeline.vision import reconcile

    assert reconcile(0, 10) == (10, None, True)
    assert reconcile(10, 0) == (10, None, True)
    assert reconcile(24, 32) == (None, (24, 32), True)


def _seed_photo_check(tmp_path, shop_id, product):
    conn = db.connect(tmp_path / "data")
    try:
        report = {"quality": "good", "image_w": 64, "image_h": 48,
                  "products": [product], "suggestions": []}
        return db.save_photo_check(
            conn, shop_id=shop_id, image_path="p1.jpg",
            report_json=json.dumps(report), cost=0.01)
    finally:
        conn.close()


def test_photo_hidden_label_and_default(tmp_path):
    _, token, shop_id = _seed_shop(tmp_path, items=())
    check_id = _seed_photo_check(tmp_path, shop_id, {
        "name_en": "potato", "name_local": None, "countable": True,
        "count": 10, "count_range": None, "needs_check": True,
        "count_spark": 10, "count_sam": 0, "boxes": [],
        "condition": None})
    html = _client(tmp_path).get(f"/e/{token}/photos/{check_id}").text
    assert "About 10 - some may be hidden, please check" in html
    assert 'value="10" data-count-for' in html


def test_photo_range_default_is_spark_count(tmp_path):
    _, token, shop_id = _seed_shop(tmp_path, items=())
    check_id = _seed_photo_check(tmp_path, shop_id, {
        "name_en": "tomato", "name_local": None, "countable": True,
        "count": None, "count_range": [24, 32], "needs_check": True,
        "count_spark": 24, "count_sam": 32, "boxes": [],
        "condition": None})
    html = _client(tmp_path).get(f"/e/{token}/photos/{check_id}").text
    assert "Between 24 and 32 - please check" in html
    assert 'value="24" data-count-for' in html


# --- 9. relative time ---

def test_format_relative_grammar():
    from app.outputs.time import format_relative

    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    assert format_relative(now, now) == "just now"
    assert format_relative(now - timedelta(seconds=59), now) == "just now"
    assert format_relative(now - timedelta(minutes=1), now) == "1 minute ago"
    assert format_relative(now - timedelta(minutes=7), now) == "7 minutes ago"
    assert format_relative(now - timedelta(hours=1), now) == "1 hour ago"
    assert format_relative(now - timedelta(hours=5), now) == "5 hours ago"
    assert format_relative(now - timedelta(hours=25), now) == "yesterday"
    assert format_relative(now - timedelta(days=3), now) == "3 days ago"


def test_web_modules_share_relative_helper():
    for name in ("seller", "main", "quotes", "photos"):
        source = Path(f"app/web/{name}.py").read_text(encoding="utf-8")
        assert "format_relative" in source, name


# --- 10. quote subtitle ---

def test_quote_subtitle_names_shop_list(tmp_path):
    from app.market.quote import Quote, QuoteLine

    _slug, _, shop_id = _seed_shop(tmp_path, name="Murugan Vegetables")
    conn = db.connect(tmp_path / "data")
    try:
        quote = Quote(
            lines=[QuoteLine(name_en="tomato", name_local="", qty=Decimal(1),
                             unit="kg", unit_price=Decimal(18),
                             per_amount=Decimal(1),
                             line_total=Decimal(18), status="priced")],
            total=Decimal(18), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        token = db.create_quote(conn, shop_id=shop_id, quote=quote)
    finally:
        conn.close()
    import html as html_lib

    html = html_lib.unescape(_client(tmp_path).get(f"/q/{token}").text)
    assert "Prices from this shop's list, set " in html
    assert "Vegetables's" not in html


# --- 11. top items with units ---

def test_top_items_show_quantity_units(tmp_path):
    from app.market.quote import Quote, QuoteLine

    _, token, shop_id = _seed_shop(tmp_path, items=())
    conn = db.connect(tmp_path / "data")
    try:
        quote = Quote(
            lines=[
                QuoteLine(name_en="ginger", name_local="", qty=Decimal(1),
                          unit="kg", unit_price=Decimal(180),
                          per_amount=Decimal(1),
                          line_total=Decimal(180), status="priced"),
                QuoteLine(name_en="coconut", name_local="", qty=Decimal(2),
                          unit="piece", unit_price=Decimal(15),
                          per_amount=Decimal(1),
                          line_total=Decimal(30), status="priced"),
            ],
            total=Decimal(210), priced_count=2, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        db.create_quote(conn, shop_id=shop_id, quote=quote, source="seller",
                        kind="bill", status="billed")
    finally:
        conn.close()
    html = _client(tmp_path).get(f"/e/{token}/bills").text
    assert "1 kg sold" in html
    assert "2 pcs sold" in html


# --- 12. market basket without a budget ---

def _seed_listed(tmp_path, name, items):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, _, _ = db.create_shop(
            conn, name=name, phone="+914400000000", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable",
            listed=True)
        drafts = [
            DraftItem(
                name_spoken=n, name_local=CANONICAL_NAMES[n], name_en=n,
                variety=None,
                price_lines=[PriceLine(Decimal(p), Decimal(a), u)],
                qty=None, qty_unit=None,
                proof=Proof(quote=f"{n} {p}", turn_ids=[1],
                            start_ms=0, end_ms=1000),
            )
            for n, p, a, u in items
        ]
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
    finally:
        conn.close()


def test_market_basket_shows_for_quantities_without_budget(tmp_path,
                                                          monkeypatch):
    from app.market.search import Query, Want

    _seed_listed(tmp_path, "Basket Shop",
                 [("onion", 25, 1, "kg"), ("ginger", 180, 1, "kg")])
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **kw: Query(
            [Want("onion", Decimal(2), "kg", None),
             Want("ginger", Decimal("0.5"), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **kw: "Basket picks.")
    html = _client(tmp_path).get(
        "/market", params={"q": "onion 2kg ginger half kg"}).text
    assert "onion" in html and "ginger" in html
    assert 'class="basket' in html
    assert "Basket Shop" in html
    assert "₹140" in html


def test_market_partial_shop_when_none_has_all(tmp_path, monkeypatch):
    from app.market.search import Query, Want

    _seed_listed(tmp_path, "Onion Shop", [("onion", 25, 1, "kg")])
    _seed_listed(tmp_path, "Ginger Shop", [("ginger", 180, 1, "kg")])
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **kw: Query(
            [Want("onion", Decimal(2), "kg", None),
             Want("ginger", Decimal("0.5"), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **kw: "Split it.")
    html = _client(tmp_path).get(
        "/market", params={"q": "onion 2kg ginger half kg"}).text
    assert "Cheapest split" in html
    assert "missing:" in html
    assert "Onion Shop" in html or "Ginger Shop" in html
