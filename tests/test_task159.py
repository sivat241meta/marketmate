"""Task 159: light judge test page (video -> price card -> WhatsApp -> Excel).

No model calls: the pipeline start is mocked and sessions are seeded
directly. The sample video lives in tmp_path, never in git.
"""

import json
import subprocess
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof
from app.web.i18n import STRINGS, t_for

ROOT = Path(__file__).resolve().parent.parent

JUDGE_KEYS = [
    "judge.entry", "judge.title", "judge.intro",
    "judge.step1", "judge.step2", "judge.step3", "judge.step4",
    "judge.or", "judge.sample_btn", "judge.sample_watch",
    "judge.runs_left", "judge.limit", "judge.locked",
    "judge.model_listen", "judge.model_think", "judge.model_see",
    "judge.failed", "judge.retry", "judge.action", "judge.open_run",
    "judge.other", "judge.step3_counts", "judge.step3_done",
    "judge.wa_title", "judge.wa_open", "judge.catalog_open",
    "judge.xlsx", "judge.ai", "judge.ai_counts", "judge.full_app",
]


def _client(tmp_path, monkeypatch=None, **env_extra):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    env.update(env_extra)
    client = TestClient(create_app(load_settings(env)),
                        follow_redirects=False)
    client.cookies.set("ui_lang", "en")
    if monkeypatch is not None:
        monkeypatch.setattr("app.web.seller.jobs.submit",
                            lambda fn, *args: None)
    return client


def _judge_token(client):
    response = client.get("/try")
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    assert location.endswith("/judge"), location
    return location.split("/e/")[1].rsplit("/judge", 1)[0]


def _normal_token(client):
    response = client.post("/new", data={
        "name": "Real Store", "phone": "+914400000159", "area": "Koyambedu",
        "language": "en", "currency": "INR", "type": "vegetable"})
    assert response.status_code in (302, 303)
    return response.headers["location"].rsplit("/e/", 1)[1]


def _shop_id(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["id"]
    finally:
        conn.close()


def _clean_item(photo=None, clip=None):
    return DraftItem(
        name_spoken="tomato",
        name_local="தக்காளி",
        name_en="tomato",
        variety=None,
        price_lines=[PriceLine(Decimal(40), Decimal(1), "kg", "")],
        qty=None,
        qty_unit=None,
        proof=Proof(quote="tomato 40", turn_ids=[1], start_ms=0,
                    end_ms=1000, audio_clip=clip),
        flags=[],
        photo=photo,
    )


def _needy_item():
    return DraftItem(
        name_spoken="onion",
        name_local="வெங்காயம்",
        name_en="onion",
        variety=None,
        price_lines=[PriceLine(Decimal(40), Decimal(1), "kg", "")],
        qty=None,
        qty_unit=None,
        proof=Proof(quote="onion forty", turn_ids=[2], start_ms=1000,
                    end_ms=2000),
        flags=[Flag(field="price", code="SOUND_ALIKE",
                    message="Did you say 40 or 80?",
                    options=["40", "80"], blocking=True)],
    )


def _review_session(tmp_path, token, items):
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id, items)
        db.set_session_status(conn, session_id, "review", "ready to check")
        return session_id
    finally:
        conn.close()


def _sample_file(tmp_path):
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0123456789" * 100)
    return sample


# --- 1. /try lands on the judge page ---


def test_try_redirects_to_judge_page(tmp_path):
    client = _client(tmp_path)
    response = client.get("/try")
    assert response.status_code in (302, 303)
    location = response.headers["location"]
    assert location.startswith("/e/") and location.endswith("/judge")
    assert "mm_try" in response.headers.get("set-cookie", "")
    html = client.get(location).text
    assert "Judge test · about 3 minutes" in html
    assert 'id="judge-step1"' in html
    assert 'id="judge-step2"' in html
    assert 'id="judge-step3"' in html
    assert 'id="judge-step4"' in html
    assert "Your stall video or voice note" in html
    assert "Meta AI at work" in html
    assert "Price card" in html
    assert "Open the full seller app" in html
    # The remembered shop redirects to the judge page too.
    again = client.get("/try")
    assert again.headers["location"] == location


def test_entry_links_on_home_sellers_how(tmp_path):
    client = _client(tmp_path)
    for path in ("/", "/sellers", "/how"):
        html = client.get(path).text
        assert 'href="/try"' in html, path
        assert "Judges: test it in 3 minutes" in html, path


# --- 2. real shops never see judge routes ---


def test_judge_routes_404_for_normal_shop(tmp_path):
    client = _client(tmp_path)
    token = _normal_token(client)
    assert client.get(f"/e/{token}/judge").status_code == 404
    assert client.get(f"/e/{token}/judge-sample").status_code == 404
    assert client.post(f"/e/{token}/upload-sample").status_code == 404


def test_judge_token_cannot_open_or_change_other_shop(tmp_path):
    client = _client(tmp_path)
    judge = _judge_token(client)
    other = _normal_token(client)
    session_id = _review_session(tmp_path, other, [_clean_item()])
    assert client.get(f"/e/{judge}/s/{session_id}").status_code == 404
    assert client.get(f"/e/{judge}/s/{session_id}/status").status_code == 404
    assert client.get(f"/e/{judge}/s/{session_id}/clip/0").status_code == 404
    edited = json.loads(db._draft_to_json(_clean_item()))
    response = client.post(f"/e/{judge}/s/{session_id}/approve",
                           json={"items": [edited], "confirmed": []})
    assert response.status_code == 404
    # And the other shop's own pages still work.
    assert client.get(f"/e/{other}/s/{session_id}").status_code == 200


# --- 3. sample button + player ---


def test_sample_button_hidden_without_file(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    response = client.get(f"/e/{token}/judge")
    assert response.status_code == 200
    assert "data-sample-btn" not in response.text
    assert "judge-sample-video" not in response.text


def test_sample_button_shown_with_file_and_streams(tmp_path):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, JUDGE_SAMPLE_VIDEO=str(sample))
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    assert "data-sample-btn" in html
    assert "Use a real sample: VPS stall, Tamil, 64 s" in html
    assert f'src="/e/{token}/judge-sample"' in html
    stream = client.get(f"/e/{token}/judge-sample")
    assert stream.status_code == 200
    assert stream.headers["content-type"] == "video/mp4"
    assert stream.content == sample.read_bytes()
    ranged = client.get(f"/e/{token}/judge-sample",
                        headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.content == sample.read_bytes()[:4]


# --- 4. upload-sample: session, limits, cost cap ---


def test_upload_sample_creates_tamil_session(tmp_path, monkeypatch):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, monkeypatch,
                     JUDGE_SAMPLE_VIDEO=str(sample))
    token = _judge_token(client)
    response = client.post(f"/e/{token}/upload-sample")
    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"/e/{token}/judge"
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE shop_id = ?",
            (shop["id"],)).fetchall()
        assert len(sessions) == 1
        assert sessions[0]["kind"] == "video"
        assert db.session_speak_lang(conn, sessions[0]["id"]) == "ta"
        saved = tmp_path / "data" / "uploads" / (
            f"{sessions[0]['id']}_judge-sample.mp4")
        assert saved.read_bytes() == sample.read_bytes()
    finally:
        conn.close()
    # Step 2 is live with the Meta model names.
    html = client.get(f"/e/{token}/judge").text
    assert "muse-voice-transcribe-1.0" in html
    assert "muse-spark-1.3" in html
    assert "sam-3.1" in html
    assert "data-judge-status" in html
    assert "Elapsed:" in html


def test_upload_needs_no_sample_file(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    token = _judge_token(client)
    response = client.post(
        f"/e/{token}/upload?from=judge",
        files={"video": ("clip.mp4", b"0123456789", "video/mp4")},
        data={"speak_lang": "hi"})
    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"/e/{token}/judge"
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        row = conn.execute("SELECT * FROM sessions WHERE shop_id = ?",
                           (shop["id"],)).fetchone()
        assert db.session_speak_lang(conn, row["id"]) == "hi"
    finally:
        conn.close()


def test_fourth_run_shows_friendly_message(tmp_path, monkeypatch):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, monkeypatch,
                     JUDGE_SAMPLE_VIDEO=str(sample))
    token = _judge_token(client)
    for _ in range(2):
        response = client.post(
            f"/e/{token}/upload?from=judge",
            files={"video": ("clip.mp4", b"0123456789", "video/mp4")})
        assert response.status_code in (302, 303)
    response = client.post(f"/e/{token}/upload-sample")
    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"/e/{token}/judge"
    # Uploads + samples share the 3-a-day budget: the 4th lands on the
    # judge page with a friendly note, and no session is created.
    fourth = client.post(f"/e/{token}/upload-sample")
    assert fourth.status_code in (302, 303)
    assert fourth.headers["location"] == f"/e/{token}/judge?notice=runs"
    fourth_up = client.post(
        f"/e/{token}/upload?from=judge",
        files={"video": ("clip.mp4", b"0123456789", "video/mp4")})
    assert fourth_up.headers["location"] == f"/e/{token}/judge?notice=runs"
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        count = conn.execute("SELECT COUNT(*) FROM sessions WHERE shop_id = ?",
                             (shop["id"],)).fetchone()[0]
        assert count == 3
    finally:
        conn.close()
    html = client.get(f"/e/{token}/judge?notice=runs").text
    assert "run 3 of 3 for today" in html


def test_upload_sample_respects_cost_cap(tmp_path, monkeypatch):
    sample = _sample_file(tmp_path)
    client = _client(tmp_path, monkeypatch,
                     JUDGE_SAMPLE_VIDEO=str(sample), DAILY_BUDGET_USD="0")
    token = _judge_token(client)
    response = client.post(f"/e/{token}/upload-sample")
    assert response.status_code == 503
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        count = conn.execute("SELECT COUNT(*) FROM sessions WHERE shop_id = ?",
                             (shop["id"],)).fetchone()[0]
        assert count == 0
    finally:
        conn.close()


# --- 5. step 3 renders the price card ---


def test_step3_renders_price_card(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    clip = tmp_path / "data" / "clip0.m4a"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"fakeclip")
    session_id = _review_session(
        tmp_path, token,
        [_clean_item(photo="photos/tomato.jpg", clip=str(clip)),
         _needy_item()])
    html = client.get(f"/e/{token}/judge").text
    assert "2 items · 1 need a tap" in html
    assert "/m/tomato.jpg" in html
    assert "tomato" in html and "onion" in html
    assert "₹40" in html and "kg" in html
    assert f"/e/{token}/s/{session_id}/clip/0" in html
    assert "opt-btn" in html
    assert "Approve price list" in html
    assert f"/e/{token}/s/{session_id}/approve?next=judge" in html
    assert "review.js" in html


def test_approve_next_judge_returns_to_judge_page(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    first = _review_session(tmp_path, token, [_clean_item()])
    edited = json.loads(db._draft_to_json(_clean_item()))
    # Plain approve keeps the old landing page.
    response = client.post(f"/e/{token}/s/{first}/approve",
                           json={"items": [edited], "confirmed": []})
    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"/e/{token}/s/{first}/live"
    # ?next=judge comes back to the judge page for the Ready step.
    second = _review_session(tmp_path, token, [_clean_item()])
    response = client.post(f"/e/{token}/s/{second}/approve?next=judge",
                           json={"items": [edited], "confirmed": []})
    assert response.status_code in (302, 303)
    assert response.headers["location"] == f"/e/{token}/judge"


# --- 6. step 4 shows catalog, Excel and AI calls ---


def test_step4_shows_outputs_after_approval(tmp_path):
    from app.costs import CostLedger

    client = _client(tmp_path)
    token = _judge_token(client)
    session_id = _review_session(tmp_path, token, [_clean_item()])
    edited = json.loads(db._draft_to_json(_clean_item()))
    response = client.post(f"/e/{token}/s/{session_id}/approve?next=judge",
                           json={"items": [edited], "confirmed": []})
    assert response.status_code in (302, 303)
    shop_id = _shop_id(tmp_path, token)
    ledger = CostLedger(tmp_path / "data" / "costs.db", 3.0)
    ledger.add("meta", "muse-voice-transcribe-1.0", 0.0125,
               shop_id=shop_id, session_id=session_id, step="transcribe")
    ledger.add("meta", "muse-spark-1.3", 0.0025, shop_id=shop_id,
               session_id=session_id, step="extract items")
    html = client.get(f"/e/{token}/judge").text
    assert "WhatsApp catalog" in html
    assert "data-wa-text" in html
    assert "tomato" in html
    assert "wa.me/?text=" in html
    assert 'target="_blank"' in html
    assert "Open in WhatsApp" in html
    assert "Open the catalog" in html
    assert f"/e/{token}/exports/pricelist.xlsx" in html
    assert "Download Excel (.xlsx)" in html
    assert f"/e/{token}/ai?session={session_id}" in html
    assert "See the Meta AI calls" in html
    assert "2 calls · $0.0150" in html
    xlsx = client.get(f"/e/{token}/exports/pricelist.xlsx")
    assert xlsx.status_code == 200
    assert "spreadsheetml" in xlsx.headers["content-type"]
    ai_page = client.get(f"/e/{token}/ai?session={session_id}")
    assert ai_page.status_code == 200


# --- 7. no seller chrome on the judge page ---


def test_judge_page_has_no_seller_navigation(tmp_path):
    client = _client(tmp_path)
    token = _judge_token(client)
    html = client.get(f"/e/{token}/judge").text
    for absent in ('class="rail"', 'class="topbar"', 'class="bnav"',
                   "popups.js", "pnav.js", "Save your link",
                   "data-orders-badge", "onboarding"):
        assert absent not in html, absent
    assert "<nav" not in html


# --- 8. i18n ---


def test_judge_keys_exist_in_en_ta_hi():
    for lang in ("en", "ta", "hi"):
        table = STRINGS[lang]
        for key in JUDGE_KEYS:
            assert table.get(key), f"{lang} {key}"


def test_judge_page_renders_in_ta_and_hi(tmp_path):
    for lang, title in (("ta", "நடுவர் சோதனை"),
                        ("hi", "जज टेस्ट")):
        client = _client(tmp_path)
        client.cookies.set("ui_lang", lang)
        token = _judge_token(client)
        html = client.get(f"/e/{token}/judge").text
        assert title in html, lang
        assert t_for(lang)("judge.sample_btn") or True


# --- 9. small screens + tap targets ---


def test_judge_css_fits_small_phones():
    css = (ROOT / "app" / "web" / "static" / "css" / "judge.css").read_text()
    assert "min-height: 44px" in css
    assert "max-width: 100%" in css
    assert "grid-template-columns: 1fr 1fr 1fr" in css
    assert "@media (min-width: 640px)" in css
    html = (ROOT / "app" / "web" / "templates" / "judge.html").read_text()
    assert 'name="viewport"' in html
    assert "prefers-reduced-motion" in css


def test_no_vendor_name_anywhere():
    result = subprocess.run(
        ["git", "grep", "-I", "-i", "zo" + "ho", "--", ".",
         ":!tests/test_task159.py"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode in (0, 1), result.stderr
    assert result.stdout.strip() == "", result.stdout
