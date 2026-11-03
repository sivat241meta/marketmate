"""Task 69: SHOPS CAN JOIN THE MARKET, MARKET PAGE IN THE v9 LOOK.

Failing-tests-first: sellers choose listing at creation and in settings
(owner only, judge shops never), and the market page gets filter chips,
shop result cards and an honest empty state.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    # Task 167: tests read today's home page at /, past the entry page.
    client.cookies.set("mm_entered", "1")
    return client


def create_shop(client, name="Banana Stall", phone="+914400000069",
                language="ta", area="Koyambedu", **extra):
    data = {"name": name, "phone": phone, "area": area,
            "language": language, "currency": "INR", "type": "vegetable"}
    data.update(extra)
    resp = client.post("/new", data=data)
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price):
    return DraftItem(
        name_spoken=name_en, name_local=name_en, name_en=name_en,
        variety=None, price_lines=[PriceLine(Decimal(price), Decimal(1),
                                             "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        confirmed=True)


def publish(tmp_path, token, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, list(drafts))
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def shop_row(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)
    finally:
        conn.close()


def set_listed(tmp_path, token, listed=True):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET listed = ? WHERE id = ?",
                     (int(listed), shop["id"]))
        conn.commit()
        return shop["slug"]
    finally:
        conn.close()


def settings_base(tmp_path, token):
    shop = shop_row(tmp_path, token)
    return {"name": shop["name"], "area": shop["area"],
            "phone": shop["phone"], "language": shop["language"],
            "currency": shop["currency"], "type": shop["type"]}


def fake_basket_query(monkeypatch):
    from app.market.search import Query, Want

    def fake_parse_query(text, **kwargs):
        return Query([Want("banana", Decimal(1), "kg", None),
                      Want("beans", Decimal(1), "kg", None)], None, None)

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **kw: "Basket picks.")


# --- 1. listing choice at creation ---


def test_new_shop_listed_by_default(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    assert shop_row(tmp_path, token)["listed"] == 1


def test_new_shop_unticked_box_creates_unlisted(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client, phone="+914400000070", listed="0")
    assert shop_row(tmp_path, token)["listed"] == 0


def test_new_shop_form_has_checked_listing_box(tmp_path):
    html = make_client(tmp_path).get("/new").text
    assert 'name="listed"' in html
    box = next(line for line in html.splitlines()
               if 'name="listed"' in line and "checkbox" in line)
    assert "checked" in box
    assert "Find a shop" in html
    assert "today&#39;s prices" in html or "today's prices" in html


def test_judge_shops_never_listed_and_no_switch(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/try")
    assert resp.status_code in (302, 303), resp.text
    token = resp.headers["location"].split("/e/")[1].rsplit("/judge", 1)[0]
    shop = shop_row(tmp_path, token)
    assert shop["is_judge"] == 1
    assert shop["listed"] == 0
    assert "Test shop - not listed in the market" in \
        client.get(f"/e/{token}").text
    assert 'name="listed"' not in client.get(f"/e/{token}/settings").text
    # Even an explicit switch value cannot list a judge shop.
    resp = client.post(f"/e/{token}/settings",
                       data={**settings_base(tmp_path, token),
                             "listed": "on"})
    assert resp.status_code in (302, 303), resp.text
    assert shop_row(tmp_path, token)["listed"] == 0


# --- 2. settings switch ---


def test_settings_switch_lists_and_unlists(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client, phone="+914400000071", listed="0")
    assert shop_row(tmp_path, token)["listed"] == 0
    html = client.get(f"/e/{token}/settings").text
    assert 'name="listed"' in html
    base = settings_base(tmp_path, token)
    resp = client.post(f"/e/{token}/settings", data={**base, "listed": "on"})
    assert resp.status_code in (302, 303), resp.text
    assert shop_row(tmp_path, token)["listed"] == 1
    resp = client.post(f"/e/{token}/settings", data=base)
    assert resp.status_code in (302, 303), resp.text
    assert shop_row(tmp_path, token)["listed"] == 0


def test_leaving_market_takes_effect_immediately(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("banana", 40), _draft("beans", 60)])
    fake_basket_query(monkeypatch)
    params = {"q": "banana 1 kg, beans 1 kg"}
    assert "Banana Stall" in client.get("/market", params=params).text
    resp = client.post(f"/e/{token}/settings",
                       data=settings_base(tmp_path, token))
    assert resp.status_code in (302, 303), resp.text
    html = client.get("/market", params=params).text
    assert "Banana Stall" not in html
    assert "No shops near you have shared today" in html


def test_settings_switch_owner_only(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    assert shop_row(tmp_path, token)["listed"] == 1
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        _helper_id, helper_token = db.create_helper(
            conn, shop["id"], "Helper")
    finally:
        conn.close()
    assert client.get(f"/e/{helper_token}/settings").status_code == 403
    resp = client.post(f"/e/{helper_token}/settings",
                       data={**settings_base(tmp_path, token)})
    assert resp.status_code == 403
    assert shop_row(tmp_path, token)["listed"] == 1


# --- 3. market finds listed shops, honest when empty ---


def test_market_finds_listed_banana_and_beans(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = shop_row(tmp_path, token)["slug"]
    publish(tmp_path, token, [_draft("banana", 40), _draft("beans", 60)])
    fake_basket_query(monkeypatch)
    html = client.get("/market",
                      params={"q": "banana 1 kg, beans 1 kg"}).text
    assert "Banana Stall" in html
    assert "banana" in html and "beans" in html
    assert "No fresh prices for" not in html
    assert "still missing" not in html
    assert f"/s/{slug}" in html
    assert f"/s/{slug}/quote" in html


def test_market_empty_state_when_nothing_listed(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client, phone="+914400000072", listed="0")
    publish(tmp_path, token, [_draft("banana", 40), _draft("beans", 60)])
    fake_basket_query(monkeypatch)
    html = client.get("/market",
                      params={"q": "banana 1 kg, beans 1 kg"}).text
    assert "No shops near you have shared today" in html
    assert "Are you a seller? Start selling" in html
    assert 'href="/new"' in html
    assert 'class="basket' not in html
    assert "totals 0" not in html
    assert "still missing" not in html


def test_market_result_cards_and_filter_row(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("banana", 40), _draft("beans", 60)])
    fake_basket_query(monkeypatch)
    html = client.get("/market",
                      params={"q": "banana 1 kg, beans 1 kg"}).text
    # One filter row: areas, open-now toggle, near-me, sort, pincode.
    assert 'name="open_now"' in html
    assert 'name="sort"' in html
    assert 'name="pincode"' in html
    assert "Near me" in html
    assert "All areas" in html
    # Result card: shop + area + total + order buttons.
    assert "Koyambedu" in html
    assert "Open shop" in html
    assert "Order these items" in html
    assert "Best" in html


def test_home_and_shop_keep_find_shop_links(tmp_path):
    client = make_client(tmp_path)
    token = create_shop(client)
    slug = shop_row(tmp_path, token)["slug"]
    publish(tmp_path, token, [_draft("banana", 40)])
    assert 'href="/market"' in client.get("/").text
    assert 'href="/market"' in client.get(f"/s/{slug}").text


# --- 4. privacy + languages ---


def _market_scripts(html):
    srcs = []
    for match in re.finditer(
            r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>', html):
        src = match.group(1).split("?")[0]
        if src.startswith("/static/"):
            path = ROOT / "app/web/static" / src[len("/static/"):]
            if path.is_file():
                srcs.append(path.read_text(encoding="utf-8"))
    for match in re.finditer(r"<script(?![^>]*src=)[^>]*>(.*?)</script>",
                             html, re.DOTALL):
        srcs.append(match.group(1))
    return srcs


def test_market_js_still_keeps_coords_on_device(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("banana", 40)])
    fake_basket_query(monkeypatch)
    html = client.get("/market",
                      params={"q": "banana 1 kg, beans 1 kg"}).text
    assert "near-me" in html
    for src in _market_scripts(html):
        has_net = ("fetch(" in src) or ("XMLHttpRequest" in src)
        has_coord = re.search(r"\b(lat|lng|latitude|longitude)\b", src,
                              re.IGNORECASE) is not None
        assert not (has_net and has_coord), src[:200]


def test_pages_render_en_ta_hi(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    token = create_shop(client)
    publish(tmp_path, token, [_draft("banana", 40), _draft("beans", 60)])
    fake_basket_query(monkeypatch)
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        assert client.get("/new").status_code == 200
        assert client.get(f"/e/{token}/settings").status_code == 200
        resp = client.get("/market",
                          params={"q": "banana 1 kg, beans 1 kg"})
        assert resp.status_code == 200, lang
        assert resp.text.strip()
    client.cookies.set("ui_lang", "ta")
    assert "சந்தை" in client.get(
        "/market", params={"q": "banana 1 kg, beans 1 kg"}).text
