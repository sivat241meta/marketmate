"""Task 45: approve works with carried items, UPI @, board tap hint, review i18n."""

from __future__ import annotations

import html as html_lib
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
QUOTE = "t45 secret quote"


def _client(tmp_path, lang="en") -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    client = TestClient(create_app(load_settings(env)), follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    return client


def _create_shop(client, name="T45 Stall", phone="+914400000045",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, per_amount=1, unit="kg", local=None):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en, name_local=local or CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None, qty_unit=None,
        proof=Proof(quote=QUOTE, turn_ids=[], start_ms=0, end_ms=0),
        confirmed=True)


def _board_draft(name_en="onion", price="35", frame=None):
    draft = _draft(name_en, price)
    draft.proof.source = "board_photo"
    if frame is not None:
        draft.proof.frame = frame
    draft.flags = [Flag(field="price", code="BOARD_CONFIRM",
                        message="read from your board – tap to confirm",
                        options=[str(price)], blocking=True)]
    return draft


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


# --- 1. carried section must not crash approve -------------------------------


def test_carried_section_uses_own_class_and_cards_have_names(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 30),
                               _draft("potato", 40)])
    session_id = _start_review_session(
        tmp_path, token, "live", [_draft("tomato", 99)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert 'class="carried-box"' in html
    form = html.split('<form id="review-form"')[1].split("</form>")[0]
    chunks = re.split(r"<section\b", form)
    cards = [c for c in chunks[1:]
             if re.match(r'[^>]*class="card(\s|")', c)]
    assert len(cards) == 1  # the real card only; carried box excluded
    for chunk in cards:
        assert "data-card=" in chunk.split(">", 1)[0]
        assert "<h2>" in chunk
        assert 'class="name-local"' in chunk
        assert 'class="name-en"' in chunk


def test_review_js_no_bare_card_selector():
    js = (ROOT / "app/web/static/review.js").read_text(encoding="utf-8")
    assert 'querySelectorAll(".card")' not in js
    assert "querySelectorAll('.card')" not in js
    assert '.card[data-card]' in js


def test_js_collect_ignores_carried_box():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "tests/js/review_collect.test.mjs"], cwd=ROOT, check=False,
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_rendered_carried_ids_match_base(tmp_path):
    """The checked carried boxes hold exactly the base ids off-session."""
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20), _draft("onion", 30),
                               _draft("potato", 40)])
    session_id = _start_review_session(
        tmp_path, token, "live", [_draft("tomato", 99)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    found = sorted(int(v) for v in re.findall(
        r'data-carried data-id="(\d+)"', html))
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        base_id = db.latest_version(conn, shop["id"], published_only=True)
        expected = sorted(i.id for i in db.version_items(conn, base_id)
                          if i.name_en != "tomato")
    finally:
        conn.close()
    assert found == expected
    assert html.count("data-carried") >= 2


# --- 2. UPI link keeps @ -----------------------------------------------------


def test_upi_link_keeps_at_unencoded():
    from app.web.bills import build_upi_url

    url = build_upi_url("lakshmi.test@upi", "Lakshmi & Sons",
                        Decimal("220.00"), 7, "Lakshmi Store")
    assert url.startswith("upi://pay?")
    assert "pa=lakshmi.test@upi&" in url
    assert "pa=lakshmi.test%40upi" not in url
    assert "am=220.00" in url
    assert "cu=INR" in url
    assert "pn=Lakshmi%20%26%20Sons" in url
    assert "tn=" in url and "Bill" in url


def test_bill_qr_payload_equals_link(tmp_path):
    from app.market.quote import WantedLine, build_quote
    from app.outputs.qr import qr_svg
    from app.web.bills import build_upi_url

    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 20)])
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        conn.execute("UPDATE shops SET upi_id=? WHERE id=?",
                     ("lakshmi.test@upi", shop["id"]))
        conn.commit()
        quote = build_quote(conn, shop["id"],
                            [WantedLine("tomato", Decimal(2), "kg", "text")])
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill", status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        row = db.get_quote_by_id(conn, bill_id)
        total, payee = row["total"], shop["upi_payee"] or shop["name"]
        shop_name = shop["name"]
    finally:
        conn.close()
    html = client.get(f"/e/{token}/bills/{bill_id}").text
    match = re.search(r'data-upi-url="([^"]+)"', html)
    assert match, "bill page must carry the UPI link"
    link = html_lib.unescape(match.group(1))
    expected = build_upi_url("lakshmi.test@upi", payee, Decimal(total),
                             bill_id, shop_name)
    assert link == expected
    assert "pa=lakshmi.test@upi&" in link
    assert qr_svg(expected) in html  # the QR on the page encodes this link


# --- 3. board-photo cards: tap the price -------------------------------------


def test_board_only_card_hides_confirm_shows_hint(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    session_id = _start_review_session(
        tmp_path, token, "board", [_board_draft()])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "data-board-hint" in html
    assert "Tap the price to confirm it" in html
    # One confirm box, kept hidden: the price tap ticks it via JS.
    assert html.count("data-card-confirm") == 1
    assert re.search(r"data-confirm-wrap hidden[^>]*>.*?data-card-confirm",
                     html, re.DOTALL)


def test_voice_card_keeps_visible_confirm(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    draft = _draft("tomato", 20)
    draft.flags = [Flag(field="price", code="UNIT_MISSING",
                        message="price is missing its unit",
                        options=[], blocking=True)]
    session_id = _start_review_session(tmp_path, token, "video", [draft])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "data-board-hint" not in html
    assert "data-confirm-wrap" not in html
    assert html.count("data-card-confirm") == 1
    assert "I confirm" in html


def test_board_card_with_extra_flag_keeps_visible_confirm(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    draft = _board_draft()
    draft.flags.append(Flag(field="price", code="UNIT_MISSING",
                            message="price is missing its unit",
                            options=[], blocking=True))
    session_id = _start_review_session(tmp_path, token, "board", [draft])
    html = client.get(f"/e/{token}/s/{session_id}").text
    assert "data-board-hint" not in html
    assert "data-confirm-wrap" not in html
    assert "I confirm" in html


# --- 4. review strings translated --------------------------------------------


NEW_KEYS = ["review.ready", "review.need_one", "review.need_many",
            "review.carried_title", "review.carried_sub",
            "review.carried_clear", "review.board_hint", "review.sold_out",
            "review.play_then_confirm", "review.approve_failed",
            "review.board_photo_alt"]


def test_review_i18n_keys_all_langs():
    from app.web.i18n import STRINGS, t_for

    for key in NEW_KEYS:
        assert key in STRINGS["en"], key
        en = t_for("en")(key, n=3, ok=1, total=2, need=1)
        for lang in ("ta", "hi"):
            assert key in STRINGS[lang], (key, lang)
            text = t_for(lang)(key, n=3, ok=1, total=2, need=1)
            assert text != en, (key, lang)
            assert any(ord(c) > 127 for c in text), (key, lang, text)
    assert (t_for("en")("review.need_many", n=5)
            == "5 items still need your choice or a tick")
    assert (t_for("en")("review.ready")
            == "All cards look right — ready to approve.")


def test_review_js_no_hardcoded_english():
    js = (ROOT / "app/web/static/review.js").read_text(encoding="utf-8")
    for needle in ("All cards look right — ready to approve.",
                   "1 item still needs your choice or a tick",
                   "items still need your choice or a tick",
                   "look right ·",
                   "prices look right",
                   "Play the clip, then tick I confirm.",
                   "Approve failed."):
        assert needle not in js, needle
    for attr in ("msgReady", "msgNeedOne", "msgNeedMany", "msgCounts",
                 "msgCountsAria"):
        assert attr in js, attr


def test_no_english_leftovers_on_tamil_review_with_carried(tmp_path):
    from app.web.i18n import t_for

    client = _client(tmp_path, lang="ta")
    token = _create_shop(client, language="ta")
    version_id = _publish(tmp_path, token, [_draft("tomato", 20),
                                            _draft("onion", 35),
                                            _draft("potato", 40)])
    conn = db.connect(tmp_path / "data")
    try:
        conn.execute("UPDATE items SET sold_out=1 WHERE version_id=? "
                     "AND name_en=?", (version_id, "potato"))
        conn.commit()
    finally:
        conn.close()
    session_id = _start_review_session(
        tmp_path, token, "board", [_board_draft(frame="board.jpg")])
    html = client.get(f"/e/{token}/s/{session_id}").text
    for needle in ("Also on your list", "These stay on your list", "Untick",
                   "Remove all of these", "Sold out",
                   "Tap the price to confirm it", "I confirm",
                   "Approve price list", "Check prices", "Check again",
                   "Needs you", "Play what you said", "Read from your board",
                   "Your price board", "All cards look right", "look right",
                   "need you", "still need", "Quantity", "Remove", "Price",
                   "Per", "Unit"):
        assert needle not in html, f"English leftover: {needle}"
    t = t_for("ta")
    for key in ("review.carried_title", "review.carried_sub",
                "review.carried_clear", "review.board_hint",
                "review.approve"):
        assert t(key) in html, key


def test_approve_form_carries_translated_messages(tmp_path):
    """data-msg-* attributes render in the UI language (Tamil here)."""
    from app.web.i18n import t_for

    client = _client(tmp_path, lang="ta")
    token = _create_shop(client, language="ta")
    session_id = _start_review_session(
        tmp_path, token, "video", [_draft("tomato", 20)])
    html = client.get(f"/e/{token}/s/{session_id}").text
    t = t_for("ta")
    for key, attr in (("review.ready", "data-msg-ready"),
                      ("review.need_one", "data-msg-need-one")):
        value = html_lib.unescape(re.search(
            rf'{attr}="([^"]+)"', html).group(1))
        assert value == t(key), (key, value)
    counts = html_lib.unescape(re.search(
        r'data-msg-counts="([^"]+)"', html).group(1))
    assert "{ok}" in counts and "{need}" in counts
    assert any(ord(c) > 127 for c in counts), counts
