"""Task 23: Fresh Market review, shop, market, update and board."""

import re
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.market.search import Query, Want
from app.models import DraftItem, Flag, PriceLine, Proof
from app.pipeline.names import CANONICAL_NAMES
from app.web.main import create_app

QUOTE = "review secret quote tomato eighteen rupees"
CONDITION = "condition-hint-must-stay-private"
BASE = "/static/app.css"


def _settings(tmp_path):
    return load_settings({"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})


def _client(tmp_path, drafts=None, monkeypatch=None):
    settings = _settings(tmp_path)
    app = create_app(settings)
    if drafts is not None and monkeypatch is not None:

        def fake_submit(fn, *args):
            fn(*args)

        def fake_process(conn, session_id, video, *, settings, ledger):
            db.save_drafts(conn, session_id, drafts)
            db.set_session_status(
                conn, session_id, "review", f"{len(drafts)} items need review"
            )

        monkeypatch.setattr("app.web.seller.jobs.submit", fake_submit)
        monkeypatch.setattr("app.web.seller.process_video_session", fake_process)
    return TestClient(app, follow_redirects=False)


def _create_shop(client):
    response = client.post(
        "/new",
        data={
            "name": "Kannan Store",
            "phone": "+914400000000",
            "area": "Koyambedu",
            "language": "ta",
            "currency": "INR",
            "type": "vegetable",
        },
    )
    assert response.status_code in (302, 303)
    return response.headers["location"]


def _clean_draft():
    return DraftItem(
        name_spoken="potato",
        name_ta="உருளைக்கிழங்கு",
        name_en="potato",
        variety=None,
        price_lines=[PriceLine(Decimal(30), Decimal(1), "kg", "kilo thirty")],
        qty=None,
        qty_unit=None,
        proof=Proof(
            quote="potato kilo thirty",
            turn_ids=[1],
            start_ms=0,
            end_ms=1000,
        ),
        flags=[],
    )


def _flagged_draft():
    return DraftItem(
        name_spoken="tomato",
        name_ta="தக்காளி",
        name_en="tomato",
        variety=None,
        price_lines=[PriceLine(Decimal(18), Decimal(1), "kg", "kilo eighteen")],
        qty=None,
        qty_unit=None,
        proof=Proof(
            quote=QUOTE,
            turn_ids=[1],
            start_ms=0,
            end_ms=1000,
            audio_clip="/tmp/clips/t23_item.m4a",
        ),
        flags=[
            Flag(
                field="price",
                code="SOUND_ALIKE",
                message="did you say 18 or 80?",
                options=["18", "80"],
            )
        ],
    )


def _review_html(tmp_path, monkeypatch):
    client = _client(tmp_path, [_clean_draft(), _flagged_draft()], monkeypatch)
    location = _create_shop(client)
    session_url = client.post(
        location + "/upload", files={"video": ("clip.mp4", b"fakevideo", "video/mp4")}
    ).headers["location"]
    return client.get(session_url).text


def test_static_url_cache_busting(tmp_path):
    html = _client(tmp_path).get("/").text
    match = re.search(r"/static/app\.css\?v=([0-9a-f]{10})", html)
    assert match, "base.html must render app.css with a ?v= query"


def test_static_url_for_js(tmp_path, monkeypatch):
    html = _review_html(tmp_path, monkeypatch)
    assert re.search(r"/static/review\.js\?v=[0-9a-f]{10}", html)
    market_html = _client(tmp_path).get("/market").text
    assert re.search(r"/static/recorder\.js\?v=[0-9a-f]{10}", market_html)


def test_review_orders_needs_before_ok(tmp_path, monkeypatch):
    html = _review_html(tmp_path, monkeypatch)
    assert "Check prices" in html
    assert "look right" in html and "need you" in html
    # Cards needing a decision (tomato, index 1) come before OK cards (potato, 0).
    assert html.index('data-card="1"') < html.index('data-card="0"')
    assert html.count("data-card-confirm") == 2
    assert "Approve price list" in html
    assert "<mark>" in html
    assert "Play what you said" in html
    assert "<progress" in html or "progress" in html


def _seed_shop(tmp_path, name="Kannan Store"):
    conn = db.connect(tmp_path / "data")
    try:
        shop_id, slug, _token = db.create_shop(
            conn,
            name=name,
            phone="+914400000000",
            area="Koyambedu",
            language="ta",
            currency="INR",
            shop_type="vegetable",
        )
        draft = DraftItem(
            name_spoken="tomato",
            name_ta="தக்காளி",
            name_en="tomato",
            variety=None,
            price_lines=[PriceLine(Decimal(18), Decimal(1), "kg", "kilo eighteen")],
            qty=None,
            qty_unit=None,
            proof=Proof(
                quote=QUOTE, turn_ids=[1], start_ms=0, end_ms=1000,
                audio_clip="/tmp/clips/t23_shop.m4a",
            ),
            condition_hint=CONDITION,
        )
        session_id = db.create_session(conn, shop_id, "video")
        version_id = db.approve(conn, session_id, [draft])
        db.set_published(conn, version_id, True)
    finally:
        conn.close()
    return slug


def test_shop_trust_line_and_no_seller_info(tmp_path):
    slug = _seed_shop(tmp_path)
    html = _client(tmp_path).get(f"/s/{slug}").text
    assert "Prices set by the seller" in html
    assert "spoken and checked" in html
    assert "Call" in html and "WhatsApp" in html
    assert "?lang=ta" in html and "?lang=en" in html
    assert QUOTE not in html
    assert CONDITION not in html
    assert "/clip/" not in html
    assert "₹18" in html


def _market_draft(name_en, price):
    return DraftItem(
        name_spoken=name_en,
        name_ta=CANONICAL_NAMES[name_en],
        name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        qty=None,
        qty_unit=None,
        proof=Proof(quote="q", turn_ids=[1], start_ms=0, end_ms=1000),
    )


def _seed_market(tmp_path):
    conn = db.connect(tmp_path / "data")
    try:
        for name, lines in (
            ("Shop A", [("tomato", 18), ("onion", 25)]),
            ("Shop B", [("tomato", 22), ("onion", 30)]),
        ):
            shop_id, _, _ = db.create_shop(
                conn,
                name=name,
                phone="+914400000000",
                area="Koyambedu",
                language="ta",
                currency="INR",
                shop_type="vegetable",
                listed=True,
            )
            session_id = db.create_session(conn, shop_id, "video")
            version_id = db.approve(
                conn,
                session_id,
                [_market_draft(item, price) for item, price in lines],
            )
            db.set_published(conn, version_id, True)
    finally:
        conn.close()


def test_market_results_and_basket(tmp_path, monkeypatch):
    _seed_market(tmp_path)

    def fake_parse_query(text, **kwargs):
        return Query(
            [Want("tomato", None, None, None), Want("onion", None, None, None)],
            Decimal(300),
            None,
        )

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    monkeypatch.setattr(
        "app.web.main.explain_basket", lambda plans, budget, **kw: "Fresh picks."
    )
    html = _client(tmp_path).get("/market", params={"q": "tomato onion"}).text
    assert "Understood" in html
    assert "Lowest" in html
    assert "Shop A" in html and "Shop B" in html
    assert "₹43" in html
    assert 'class="basket' in html or "basket" in html
    assert "(assumed 1 kg)" in html
    assert "Fresh picks." in html


def test_market_unknown_polite(tmp_path, monkeypatch):
    _seed_market(tmp_path)

    def fake_parse_query(text, **kwargs):
        return Query([], None, None, unknown=["dragonfruit"])

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    html = _client(tmp_path).get("/market", params={"q": "dragonfruit"}).text
    assert "dragonfruit" in html
    assert "understood" in html.lower()


def test_no_inline_styles(tmp_path, monkeypatch):
    review_html = _review_html(tmp_path, monkeypatch)
    assert "style=" not in review_html
    slug = _seed_shop(tmp_path)
    client = _client(tmp_path)
    assert "style=" not in client.get(f"/s/{slug}").text
    assert "style=" not in client.get("/market").text
    location = _create_shop(client)
    assert "style=" not in client.get(location + "/update").text
