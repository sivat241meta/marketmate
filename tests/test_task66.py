"""Task 66: the seller can change a product's name.

Check page + live list rename, names remembered for the next list and for
billing. A rename never touches prices, price lines, voice-clip proof or the
"said" text.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
QUOTE = "t66 vazhai pazham kilo eighty rupees"

NEW_LOCAL = "கற்பூரவல்லி வாழைப்பழம்"
NEW_EN = "Karpooravalli banana"
NEW_VARIETY = "karpooravalli"


def _client(tmp_path, lang="en") -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    return client


def _create_shop(client, name="T66 Stall", phone="+914400000066",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en="banana", price=80, local="வாழைப்பழம்", variety="poovan",
           quote=QUOTE):
    return DraftItem(
        name_spoken=name_en, name_local=local, name_en=name_en,
        variety=variety,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg",
                               "kilo eighty")],
        qty=None, qty_unit=None,
        proof=Proof(quote=quote, turn_ids=[1], start_ms=0, end_ms=1000),
        confirmed=True)


def _publish(tmp_path, token, drafts) -> int:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
        return version_id
    finally:
        conn.close()


def _start_review_session(tmp_path, token, kind, drafts):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], kind)
        db.save_drafts(conn, session_id, drafts)
        db.set_session_status(conn, session_id, "review",
                              f"{len(drafts)} items need review")
        return session_id
    finally:
        conn.close()


def _conn(tmp_path) -> sqlite3.Connection:
    return db.connect(tmp_path / "data")


def _approve_body(drafts, local=None, en=None, variety=None):
    items = []
    for draft in drafts:
        items.append({
            "name_spoken": draft.name_en,
            "name_local": local if local is not None else draft.name_local,
            "name_en": en if en is not None else draft.name_en,
            "variety": variety if variety is not None else draft.variety,
            "price_lines": [{
                "said": "", "price": str(line.price),
                "per_amount": str(line.per_amount), "unit": line.unit}
                for line in draft.price_lines],
            "range_said": False, "qty": None, "qty_unit": None,
            "proof": {"quote": "", "turn_ids": [], "start_ms": 0,
                      "end_ms": 0, "frame": None, "audio_clip": None,
                      "source": None},
            "flags": [], "photo": None, "condition_hint": None,
            "confirmed": False,
        })
    return {"items": items,
            "confirmed": list(range(len(items))), "carried": []}


# --- 1. check page: edit-name button + three fields ---------------------------


def test_check_page_has_edit_name_buttons_and_fields(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _start_review_session(
        tmp_path, token, "video", [_draft(), _draft("tomato", 20,
                                                   "தக்காளி", None)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    cards = re.findall(r'<section class="card review-card[^>]*>', html)
    assert len(cards) == 2
    assert html.count("data-rename-open") == 2
    assert html.count("data-rename-form") == 2
    assert 'name="name_local" lang="ta"' in html
    assert 'name="name_en"' in html
    assert 'name="variety"' in html
    assert "data-rename-save" in html
    assert "data-rename-cancel" in html


def test_rename_on_check_page_survives_approve(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    drafts = [_draft()]
    session_id = _start_review_session(tmp_path, token, "video", drafts)
    before_lines = [(str(line.price), str(line.per_amount), line.unit,
                     line.said) for line in drafts[0].price_lines]
    before_proof = json.loads(db._draft_to_json(drafts[0]))["proof"]
    body = _approve_body(drafts, local=NEW_LOCAL, en=NEW_EN,
                         variety=NEW_VARIETY)
    resp = client.post(f"/e/{token}/s/{session_id}/approve", json=body)
    assert resp.status_code in (302, 303), resp.text
    conn = _conn(tmp_path)
    try:
        version_id = db.latest_version(conn,
                                       db.shop_by_token(conn, token)["id"],
                                       published_only=True)
        items = db.version_items(conn, version_id)
        assert items[0].name_local == NEW_LOCAL
        assert items[0].name_en == NEW_EN
        assert items[0].variety == NEW_VARIETY
        after_lines = [(str(line.price), str(line.per_amount), line.unit,
                        line.said) for line in items[0].price_lines]
        assert after_lines == before_lines
        row = conn.execute("SELECT proof FROM items WHERE id = ?",
                           (items[0].id,)).fetchone()
        assert json.loads(row["proof"]) == before_proof
    finally:
        conn.close()
    shop = _conn(tmp_path)
    try:
        slug = db.shop_by_token(shop, token)["slug"]
    finally:
        shop.close()
    html = client.get(f"/s/{slug}").text
    assert NEW_LOCAL in html
    assert NEW_EN in html


# --- 2. live rename route -----------------------------------------------------


def _snapshot(conn, version_id):
    items = conn.execute(
        "SELECT id, version_id, name_local, name_en, variety, qty, qty_unit,"
        " photo, sold_out, proof FROM items WHERE version_id = ? ORDER BY id",
        (version_id,)).fetchall()
    lines = conn.execute(
        "SELECT item_id, price, per_amount, unit, said FROM price_lines"
        " WHERE item_id IN (SELECT id FROM items WHERE version_id = ?)"
        " ORDER BY item_id, id", (version_id,)).fetchall()
    return ([tuple(row) for row in items],
            [tuple(row) for row in lines])


def test_live_rename_changes_only_names(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft(), _draft("tomato", 20,
                                                             "தக்காளி",
                                                             None)])
    conn = _conn(tmp_path)
    try:
        shop_id = db.shop_by_token(conn, token)["id"]
        item_id = db.version_items(conn, version_id)[0].id
        before_items, before_lines = _snapshot(conn, version_id)
        versions_before = conn.execute(
            "SELECT COUNT(*) FROM versions WHERE shop_id = ?",
            (shop_id,)).fetchone()[0]
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN,
        "variety": NEW_VARIETY})
    assert resp.status_code in (302, 303), resp.text
    assert resp.headers["location"].startswith(f"/e/{token}")
    conn = _conn(tmp_path)
    try:
        after_items, after_lines = _snapshot(conn, version_id)
        assert after_lines == before_lines
        assert len(after_items) == len(before_items)
        for before, after in zip(before_items, after_items):
            if before[0] == item_id:
                assert after[2] == NEW_LOCAL
                assert after[3] == NEW_EN
                assert after[4] == NEW_VARIETY
                assert before[:2] + before[5:] == after[:2] + after[5:]
            else:
                assert before == after
        versions_after = conn.execute(
            "SELECT COUNT(*) FROM versions WHERE shop_id = ?",
            (shop_id,)).fetchone()[0]
        assert versions_after == versions_before
        slug = db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()
    assert NEW_LOCAL in client.get(f"/s/{slug}").text
    home = client.get(f"/e/{token}?renamed=1").text
    assert "Name changed" in home


def test_live_rename_owner_only(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft()])
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        item_id = db.version_items(conn, version_id)[0].id
        _, helper = db.create_helper(conn, shop["id"], "Muthu")
    finally:
        conn.close()
    resp = client.post(f"/e/{helper}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN, "variety": ""})
    assert resp.status_code == 403
    assert client.post("/e/bad-token/item/1/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN}).status_code == 404
    assert client.get(f"/e/{token}/item/{item_id}/name").status_code == 405


@pytest.mark.parametrize("local,en,variety", [
    ("x" * 41, "Banana", ""),  # local too long
    ("வாழைப்பழம்", "y" * 41, ""),  # English too long
    ("வாழைப்பழம்", "Banana", "v" * 31),  # variety too long
    ("12345", "Banana", ""),  # digits only
    ("!!!", "Banana", ""),  # punctuation only
    ("வாழை ₹60", "Banana", ""),  # price-like local
    ("வாழைப்பழம்", "Banana 60/kg", ""),  # price-like English
    ("केला", "Banana", ""),  # wrong script for a Tamil shop
])
def test_live_rename_rejects_invalid_names(tmp_path, local, en, variety):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft()])
    conn = _conn(tmp_path)
    try:
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": local, "name_en": en, "variety": variety})
    assert resp.status_code == 400, (local, en, variety, resp.text[:300])
    conn = _conn(tmp_path)
    try:
        item = db.version_items(conn, version_id)[0]
        assert item.name_local == "வாழைப்பழம்"
        assert item.name_en == "banana"
    finally:
        conn.close()


def test_live_rename_allows_latin_local_name(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft()])
    conn = _conn(tmp_path)
    try:
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": "Karpooravalli", "name_en": NEW_EN, "variety": ""})
    assert resp.status_code in (302, 303), resp.text


def test_rename_audit_logged_and_hidden_from_customers(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft()])
    conn = _conn(tmp_path)
    try:
        item_id = db.version_items(conn, version_id)[0].id
        slug = db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()
    client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN, "variety": NEW_VARIETY})
    conn = _conn(tmp_path)
    try:
        events = db.list_name_changes(conn,
                                      db.shop_by_token(conn, token)["id"])
        assert len(events) == 1
        event = events[0]
        assert event["item_id"] == item_id
        assert event["old_local"] == "வாழைப்பழம்"
        assert event["new_local"] == NEW_LOCAL
        assert event["created_at"]
    finally:
        conn.close()
    assert "rename" not in client.get(f"/s/{slug}").text.lower()


# --- 3. bills keep snapshots; new bills match the new name --------------------


def _tap_bill(client, token):
    return client.post(f"/e/{token}/bills/new", data={
        "name_en_0": "banana (poovan)", "qty_0": "1", "unit_0": "kg"})


def test_old_bill_keeps_name_new_bills_match(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft(price=80)])
    resp = _tap_bill(client, token)
    assert resp.status_code in (302, 303), resp.text
    old_bill_id = resp.headers["location"].rsplit("/", 1)[1]
    conn = _conn(tmp_path)
    try:
        old_lines = json.loads(conn.execute(
            "SELECT lines_json FROM quotes WHERE id = ?",
            (old_bill_id,)).fetchone()["lines_json"])
        assert old_lines[0]["name_en"] == "banana"
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN,
        "variety": NEW_VARIETY})
    assert resp.status_code in (302, 303), resp.text
    old_html = client.get(f"/e/{token}/bills/{old_bill_id}").text
    assert "Banana (Poovan)" in old_html
    conn = _conn(tmp_path)
    try:
        kept = json.loads(conn.execute(
            "SELECT lines_json FROM quotes WHERE id = ?",
            (old_bill_id,)).fetchone()["lines_json"])
        assert kept == old_lines
    finally:
        conn.close()
    typed = client.post(f"/e/{token}/bills/new",
                        data={"items": f"{NEW_LOCAL} 1 kg"})
    assert typed.status_code in (302, 303), typed.text[:500]
    new_bill_id = typed.headers["location"].rsplit("/", 1)[1]
    conn = _conn(tmp_path)
    try:
        new_lines = json.loads(conn.execute(
            "SELECT lines_json FROM quotes WHERE id = ?",
            (new_bill_id,)).fetchone()["lines_json"])
        assert new_lines[0]["status"] == "priced"
        assert new_lines[0]["name_en"] == NEW_EN
    finally:
        conn.close()


def test_new_customer_order_uses_new_name(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft(price=80)])
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN,
        "variety": NEW_VARIETY})
    resp = client.post(f"/s/{shop['slug']}/quote", data={
        "items": f"{NEW_LOCAL} 1 kg", "customer_name": "Priya",
        "customer_phone": "+919800000001"})
    assert resp.status_code in (302, 303), resp.text[:500]
    quote_url = resp.headers["location"]
    html = client.get(quote_url).text
    assert NEW_EN in html or NEW_LOCAL in html


def test_local_parse_and_quote_match_renamed_item(tmp_path):
    from app.market.order_parse import parse_order
    from app.market.quote import WantedLine, build_quote

    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft(price=80)])
    conn = _conn(tmp_path)
    try:
        shop_id = db.shop_by_token(conn, token)["id"]
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN,
        "variety": NEW_VARIETY})
    conn = _conn(tmp_path)
    try:
        items = db.version_items(conn, version_id)
        aliases = db.shop_name_aliases(conn, shop_id)
        wanted, leftover = parse_order(f"{NEW_LOCAL} 1 kg", items, "ta",
                                       aliases=aliases)
        assert len(wanted) == 1
        assert not leftover
        quote = build_quote(conn, shop_id, [
            WantedLine(name_en=NEW_LOCAL, qty=Decimal(1), unit="kg",
                       source="voice")])
        assert quote.lines[0].status == "priced"
        assert quote.lines[0].name_en == NEW_EN
        assert quote.lines[0].line_total == Decimal("80.00")
    finally:
        conn.close()


# --- 4. remembered names ------------------------------------------------------


def test_next_session_uses_remembered_name(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft(price=80)])
    conn = _conn(tmp_path)
    try:
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN,
        "variety": NEW_VARIETY})
    session_id = _start_review_session(
        tmp_path, token, "video",
        [_draft(price=85, local="வாழைப்பழம்", variety="karpooravalli")])
    conn = _conn(tmp_path)
    try:
        drafts = db.load_drafts(conn, session_id)
        assert drafts[0].name_local == NEW_LOCAL
        assert drafts[0].name_en == NEW_EN
        assert str(drafts[0].price_lines[0].price) == "85"
    finally:
        conn.close()
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "your name" in html.lower()


def test_check_page_rename_is_remembered_on_approve(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    drafts = [_draft()]
    session_id = _start_review_session(tmp_path, token, "video", drafts)
    body = _approve_body(drafts, local=NEW_LOCAL, en=NEW_EN,
                         variety=NEW_VARIETY)
    assert client.post(
        f"/e/{token}/s/{session_id}/approve", json=body).status_code in (
        302, 303)
    next_id = _start_review_session(
        tmp_path, token, "video",
        [_draft(price=90, local="வாழைப்பழம்", variety="karpooravalli")])
    conn = _conn(tmp_path)
    try:
        again = db.load_drafts(conn, next_id)
        assert again[0].name_local == NEW_LOCAL
        assert again[0].name_en == NEW_EN
    finally:
        conn.close()


# --- 5. tiles, i18n, js -------------------------------------------------------


def test_letter_tile_uses_new_local_name(tmp_path):
    from app.web.i18n import first_grapheme

    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft()])
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    local = "கொத்தமல்லி இலை"
    client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": local, "name_en": "Coriander leaves", "variety": ""})
    assert first_grapheme(local) == "கொ"
    html = client.get(f"/s/{shop['slug']}").text
    assert "கொ<" in html or ">கொ<" in html
    home = client.get(f"/e/{token}").text
    assert "கொ<" in home or ">கொ<" in home


@pytest.mark.parametrize("lang", ["en", "ta", "hi"])
def test_pages_render_in_all_languages(tmp_path, lang):
    client = _client(tmp_path, lang=lang)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft()])
    session_id = _start_review_session(tmp_path, token, "video", [_draft()])
    conn = _conn(tmp_path)
    try:
        slug = db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()
    for url in (f"/e/{token}", f"/e/{token}/s/{session_id}",
                f"/s/{slug}?lang={lang if lang != 'en' else 'en'}"):
        resp = client.get(url)
        assert resp.status_code == 200, (lang, url)
        assert "rename." not in resp.text, (lang, url)


def test_seller_list_has_rename_buttons(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft()])
    html = client.get(f"/e/{token}").text
    assert "data-rename-open" in html
    assert "/item/" in html and "/name" in html


def test_cart_order_finds_renamed_item(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    version_id = _publish(tmp_path, token, [_draft(price=80)])
    conn = _conn(tmp_path)
    try:
        shop = db.shop_by_token(conn, token)
        item_id = db.version_items(conn, version_id)[0].id
    finally:
        conn.close()
    client.post(f"/e/{token}/item/{item_id}/name", data={
        "name_local": NEW_LOCAL, "name_en": NEW_EN,
        "variety": NEW_VARIETY})
    resp = client.post(f"/s/{shop['slug']}/quote", json={
        "lines": [{"name_en": NEW_EN, "variety": NEW_VARIETY,
                   "qty": 2, "unit": "kg"}],
        "customer_name": "Ravi", "customer_phone": "+919800000002"})
    assert resp.status_code == 200, resp.text
    html = client.get(resp.json()["url"]).text
    assert NEW_EN in html
    assert "160" in html


def test_node_check_changed_js():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    for name in ("review.js", "live.js"):
        path = ROOT / "app/web/static" / name
        if path.exists():
            proc = subprocess.run(
                [node, "--check", str(path)], cwd=ROOT, check=False,
                capture_output=True, text=True, timeout=60)
            assert proc.returncode == 0, (name, proc.stdout + proc.stderr)
