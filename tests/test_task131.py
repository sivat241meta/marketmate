"""Task 131: sellers can always upload a saved video/voice note; uploads never stuck.

Pins: dashboard upload before AND after publishing (compact "Update
today's prices" card), /live always-visible upload section, composer
speak_lang chip on seller pages, composer stops polling on language_check
and shows the question, "Done" only for done statuses, every file input
reachable, and visible upload errors.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Flag, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
COMPOSER_JS = ROOT / "app" / "web" / "static" / "composer.js"
UPLOAD_JS = ROOT / "app" / "web" / "static" / "upload.js"
ACCEPT = "video/*,audio/*,.opus,.ogg,.oga,.m4a,.mp3,.aac,.wav,.amr"


def _client(tmp_path, **env) -> TestClient:
    from app.web.main import create_app

    base = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    base.update(env)
    return TestClient(create_app(load_settings(base)),
                      follow_redirects=False)


def _create_shop(client, language="ta"):
    resp = client.post("/new", data={
        "name": "T131 Store", "phone": "+914400000131", "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _shop(tmp_path, token):
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)
    finally:
        conn.close()


def _publish(tmp_path, token):
    from app.pipeline.names import CANONICAL_NAMES

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        draft = DraftItem(
            name_spoken="tomato", name_local=CANONICAL_NAMES["tomato"],
            name_en="tomato", variety=None,
            price_lines=[PriceLine(Decimal(40), Decimal(1), "kg")],
            qty=None, qty_unit=None,
            proof=Proof(quote="tomato 40", turn_ids=[], start_ms=0,
                        end_ms=0),
            confirmed=True)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, [draft])
        db.set_published(conn, version_id, True)
        return session_id
    finally:
        conn.close()


def _review_session(tmp_path, token):
    from app.pipeline.names import CANONICAL_NAMES

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        needy = DraftItem(
            name_spoken="onion", name_local=CANONICAL_NAMES["onion"],
            name_en="onion", variety=None,
            price_lines=[PriceLine(None, Decimal(1), "kg")],
            qty=None, qty_unit=None,
            proof=Proof(quote="onion", turn_ids=[], start_ms=0, end_ms=0),
            flags=[Flag(field="price", code="NO_PRICE", message="need",
                        options=["10"], blocking=True)])
        session_id = db.create_session(conn, shop["id"], "video")
        db.save_drafts(conn, session_id, [needy])
        db.set_session_status(conn, session_id, "review", "waiting")
        return session_id
    finally:
        conn.close()


def _upload_forms(html, token):
    return re.findall(
        rf'<form[^>]*action="/e/{re.escape(token)}/upload"[^>]*>.*?</form>',
        html, re.DOTALL)


# --- 1. dashboard always has an upload entry ---------------------------------


def test_dashboard_first_run_has_upload_form(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    html = client.get(f"/e/{token}").text
    forms = _upload_forms(html, token)
    assert forms, "first-run dashboard lost its upload form"
    form = forms[0]
    assert 'id="clip"' in form
    assert 'name="video"' in form
    assert f'accept="{ACCEPT}"' in form
    assert 'name="speak_lang"' in form
    assert 'value="ta" selected' in form  # shop-language default
    for hook in ("data-upload-form", "data-max-bytes", "data-upload-name",
                 "data-upload-file", "data-upload-error",
                 "data-upload-progress", "data-upload-bar",
                 "data-upload-meta", "data-upload-cancel"):
        assert hook in form, hook


def test_dashboard_after_publish_has_compact_upload(tmp_path):
    from app.web.i18n import t_for

    client = _client(tmp_path)
    token = _create_shop(client, language="en")
    _publish(tmp_path, token)
    html = client.get(f"/e/{token}").text
    assert 'id="update-today"' in html
    title = t_for("en")("dash.update_today").replace("'", "&#39;")
    assert title in html
    forms = _upload_forms(html, token)
    assert forms, "published dashboard lost its upload form"
    form = forms[0]
    assert 'id="clip-update"' in form
    assert 'id="clip"' not in form  # second form keeps its own id
    assert 'name="video"' in form
    assert f'accept="{ACCEPT}"' in form
    assert 'name="speak_lang"' in form
    assert 'id="speak-lang-update"' in form
    for hook in ("data-upload-form", "data-max-bytes", "data-upload-name",
                 "data-upload-file", "data-upload-error",
                 "data-upload-progress", "data-upload-bar",
                 "data-upload-meta", "data-upload-cancel"):
        assert hook in form, hook


def test_dashboard_taps_state_keeps_upload(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token)
    _review_session(tmp_path, token)
    html = client.get(f"/e/{token}").text
    assert _upload_forms(html, token), "taps dashboard lost its upload form"


def test_try_demo_shop_has_upload(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/try")
    assert resp.status_code in (302, 303), resp.text
    html = client.get(resp.headers["location"]).text
    assert 'type="file"' in html and 'name="video"' in html


def test_new_upload_after_publish_makes_new_session(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="en")
    first = _publish(tmp_path, token)
    resp = client.post(
        f"/e/{token}/upload", files={"video": ("clip.mp4", b"0123456789")},
        data={"speak_lang": "ta"})
    assert resp.status_code in (302, 303), resp.text
    session_id = int(resp.headers["location"].rsplit("/s/", 1)[1])
    assert session_id != first
    conn = db.connect(tmp_path / "data")
    try:
        assert db.session_speak_lang(conn, session_id) == "ta"
    finally:
        conn.close()


# --- 2. /live always shows an upload ------------------------------------------


def test_live_always_shows_upload_composer(tmp_path):
    from app.web.i18n import t_for

    client = _client(tmp_path)
    token = _create_shop(client, language="en")
    html = client.get(f"/e/{token}/live").text
    t = t_for("en")
    section = re.search(
        r'<section[^>]*data-live-upload[^>]*>(.*?)</section>', html,
        re.DOTALL)
    assert section, "no always-visible upload section on /live"
    assert "hidden" not in section.group(0).split(">", 1)[0]
    assert t("live.upload_section") in section.group(0)
    body = section.group(1)
    assert "data-composer" in body
    assert f'action="/e/{token}/upload"' in body
    assert "data-composer-plus" in body
    for key in ("composer.upload_recording", "composer.upload_video",
                "composer.take_video"):
        assert t(key) in body, key
    # The fallback behaviour is kept as is.
    assert "data-live-fallback" in html
    fallback = re.search(
        r'<div[^>]*data-live-fallback[^>]*>(.*?)</div>\s*<p class="notice">',
        html, re.DOTALL)
    assert fallback and "data-composer" in fallback.group(1)


# --- 3a. seller composers send speak_lang --------------------------------------


def _composer_form(html, action):
    matches = re.findall(
        r'<form[^>]*data-composer-form[^>]*>.*?</form>', html, re.DOTALL)
    forms = [form for form in matches if f'action="{action}"' in form]
    assert forms, f"composer posting to {action} missing"
    return forms[0]


def _seller_pages(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    _publish(tmp_path, token)
    return client, token


def test_seller_composers_carry_speak_lang(tmp_path):
    from app.web.i18n import t_for

    client, token = _seller_pages(tmp_path)
    pages = [(f"/e/{token}/live", f"/e/{token}/upload"),
             (f"/e/{token}/update", f"/e/{token}/update"),
             (f"/e/{token}/purchases", f"/e/{token}/purchases/voice"),
             (f"/e/{token}/bills/new", f"/e/{token}/bills/new")]
    t = t_for("ta")
    for url, action in pages:
        html = client.get(url).text
        form = _composer_form(html, action)
        assert 'name="speak_lang"' in form, url
        assert 'value="ta"' in form, url  # shop-language default
        assert "data-composer-lang-chip" in html, url
        assert "தமிழ்" in html, url  # chip shows the native name
        assert t("composer.lang_aria") in html, url
        # The chip menu carries the dashboard language list.
        for code in ("ta", "en", "hi"):
            assert f'data-code="{code}"' in html, (url, code)
        # Too-big guard data for item 5.
        assert "data-max-bytes" in html, url
        assert t("composer.too_big") in html, url


def test_composer_status_node_tests():
    node = shutil.which("node")
    assert node, "node is required"
    result = subprocess.run([node, "tests/js/composer_status.test.mjs"],
                            cwd=ROOT, check=False, capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# --- 3b/3c. polling, questions, Done -------------------------------------------


def test_session_status_flags_language_check(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="en")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, session_id, "processing",
                              "We heard Kannada letters.")
        db.set_stage(conn, session_id, "language_check", detail="Kannada")
    finally:
        conn.close()
    transcript = (tmp_path / "data" / "sessions" / str(session_id)
                  / "transcript.json")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text('{"text": "thakkali nappatu", "turns": []}')
    resp = client.get(f"/e/{token}/s/{session_id}/status")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stage"] == "language_check"
    assert data["needs_action"] is True
    assert data["quote"] == "thakkali nappatu"
    assert data["language_url"] == f"/e/{token}/s/{session_id}/language"


def test_language_answer_accepts_json_for_composer(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client, language="en")
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, session_id, "processing", "heard other")
        db.set_stage(conn, session_id, "language_check", detail="other")
    finally:
        conn.close()
    resp = client.post(f"/e/{token}/s/{session_id}/language",
                       data={"speak_lang": "ta"},
                       headers={"Accept": "application/json"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processing"


def test_poll_shows_question_instead_of_hanging():
    source = COMPOSER_JS.read_text()
    # pollStatus branches on the pure statusView read...
    poll = source.split("function pollStatus")[1].split("function postForm")[0]
    assert "statusView(data)" in poll
    assert "view.kind === \"needs_action\"" in poll
    assert "showNeedsAction(ctx, bubble, data, finalUrl, statusUrl)" in poll
    assert "setStep(bubble, view.step)" in poll
    # ...and the question branch schedules no further poll.
    question = source.split("function showNeedsAction")[1].split(
        "function answerLanguage")[0]
    assert "setTimeout" not in question
    assert "pollStatus" not in question
    # The bubble shows the message, the transcript snippet and either
    # inline language buttons or the Choose-language link.
    assert "composer-quote" in question
    assert "composer-lang-pick" in question
    assert "chooseLanguage" in question
    # Answering posts speak_lang, then resumes polling.
    answer = source.split("function answerLanguage")[1].split(
        "function initComposer")[0]
    assert 'form.append("speak_lang", code)' in answer
    assert "pollStatus(ctx, bubble, statusUrl, finalUrl, 0)" in answer
    # The session page also reloads into the question instead of spinning.
    session_src = (ROOT / "app" / "web" / "templates"
                   / "session.html").read_text()
    assert "language_check" in session_src


def test_done_only_for_done_statuses():
    source = COMPOSER_JS.read_text()
    assert source.count("view.kind === \"done\"") == 2
    calls = re.findall(r"^\s+showDone\(ctx", source, re.MULTILINE)
    assert len(calls) == 2, calls
    assert "showOpenLink(ctx, bubble" in source
    opener = source.split("function showOpenLink")[1].split(
        "function langOptions")[0]
    assert "ctx.str.done" not in opener  # never prints "Done" when pending
    assert "stillWorking" in opener


# --- 4. every file input is reachable ------------------------------------------


class _Walker(HTMLParser):
    """File inputs with their label text and hidden-ancestor chains."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.inputs = []
        self.for_labels = {}
        self.parent_labels = {}
        self.methods = set()
        self.panels = set()
        self._seq = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._seq += 1
        self.stack.append([tag, attrs, "", self._seq])
        if tag == "button" and attrs.get("data-method"):
            self.methods.add(attrs["data-method"])
        if attrs.get("data-panel"):
            self.panels.add(attrs["data-panel"])
        if tag == "input" and (attrs.get("type") or "").lower() == "file":
            hidden = [dict(s[1]) for s in self.stack if "hidden" in s[1]]
            in_label = [s[3] for s in self.stack if s[0] == "label"]
            self.inputs.append({
                "id": attrs.get("id"), "name": attrs.get("name"),
                "in_label": in_label,
                "hidden": hidden, "label_text": "",
            })
        if tag in ("input", "img", "br", "meta", "link"):
            self.stack.pop()

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            _tag, attrs, text, seq = self.stack.pop()
            if tag == "label":
                if attrs.get("for"):
                    self.for_labels[attrs["for"]] = (
                        " ".join(text.split()),
                        [dict(s[1]) for s in self.stack if "hidden" in s[1]])
                self.parent_labels[seq] = " ".join(text.split())
            if self.stack:
                self.stack[-1][2] += text
        else:
            while self.stack and self.stack[-1][0] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2] += data


def _hidden_ok(html, entry, walker):
    """Every hidden ancestor must be openable in one tap (tab/+/dialog)."""
    chains = [entry["hidden"]]
    if entry["id"] and entry["id"] in walker.for_labels:
        _text, label_hidden = walker.for_labels[entry["id"]]
        chains.append(label_hidden)
    for chain in chains:
        for attrs in chain:
            if attrs.get("data-panel"):
                if attrs["data-panel"] not in walker.methods:
                    return False
            elif "data-live-fallback" in attrs:
                continue  # shown when live mode is unsupported
            elif "data-composer-video-only" in attrs:
                if "data-composer-plus" not in html:
                    return False  # unhidden by composer.js init
            elif attrs.get("id") in ("search-pop", "search-voice"):
                opener = ("data-search-open" if attrs.get("id")
                          == "search-pop" else "data-voice-toggle")
                if opener not in html:
                    return False
            elif "mm-pop" in (attrs.get("class") or ""):
                if "data-search-open" not in html:
                    return False
            elif "mm-voice" in (attrs.get("class") or ""):
                if "data-voice-toggle" not in html:
                    return False
            else:
                return False
    return True


def _label_text(html, entry, walker):
    if entry["id"] and entry["id"] in walker.for_labels:
        return walker.for_labels[entry["id"]][0]
    for seq in entry["in_label"]:
        if walker.parent_labels.get(seq):
            return walker.parent_labels[seq]
    return ""


def test_every_file_input_reachable(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _shop(tmp_path, token)["slug"]
    _publish(tmp_path, token)
    review_id = _review_session(tmp_path, token)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        purchase_id = db.create_session(conn, shop["id"], "purchase")
        db.set_session_status(conn, purchase_id, "review", "waiting")
        bill_id = db.create_session(conn, shop["id"], "bill_voice")
    finally:
        conn.close()
    pages = [f"/e/{token}", f"/e/{token}/live", f"/e/{token}/update",
             f"/e/{token}/bills/new", f"/e/{token}/purchases",
             f"/e/{token}/photos", f"/e/{token}/settings",
             f"/e/{token}/s/{review_id}",
             f"/e/{token}/purchases/{purchase_id}",
             f"/e/{token}/bills/new/{bill_id}",
             f"/s/{slug}/quote", "/market"]
    must_have_inputs = {f"/e/{token}", f"/e/{token}/live",
                        f"/e/{token}/update", f"/e/{token}/bills/new",
                        f"/e/{token}/purchases", f"/e/{token}/photos",
                        f"/e/{token}/settings", f"/e/{token}/s/{review_id}",
                        f"/s/{slug}/quote", "/market"}
    for url in pages:
        resp = client.get(url)
        assert resp.status_code == 200, (url, resp.status_code)
        walker = _Walker()
        walker.feed(resp.text)
        if url in must_have_inputs:
            assert walker.inputs, f"{url} lost its file input"
        for entry in walker.inputs:
            text = _label_text(resp.text, entry, walker)
            assert text, f"{url}: file input has no label: {entry}"
            assert _hidden_ok(resp.text, entry, walker), (
                f"{url}: file input unreachable: {entry}")


def test_bills_photo_tab_makes_photo_reachable(tmp_path):
    client, token = _seller_pages(tmp_path)
    html = client.get(f"/e/{token}/bills/new").text
    assert 'data-method="photo"' in html
    panel = re.search(
        r'<section[^>]*data-panel="photo"[^>]*>(.*?)</section>', html,
        re.DOTALL)
    assert panel, "photo panel missing"
    assert 'name="photo"' in panel.group(1)
    assert "drop-zone" in panel.group(1)


# --- 5. upload errors are visible -------------------------------------------------


def test_oversize_upload_rejected_with_message(tmp_path):
    client = _client(tmp_path, MAX_UPLOAD_BYTES="10")
    token = _create_shop(client)
    resp = client.post(f"/e/{token}/upload",
                       files={"video": ("big.mp4", b"x" * 64)},
                       data={"speak_lang": "ta"})
    assert resp.status_code == 413, resp.status_code
    assert len(resp.text.strip()) > 0


def test_upload_error_hooks_present():
    source = UPLOAD_JS.read_text()
    assert "data-upload-error" in source
    assert "extractError" in source
    composer = COMPOSER_JS.read_text()
    assert "showBlocked" in composer
    assert "fileTooBig" in composer
    assert "ctx.str.tooBig" in composer


# --- strings, languages, assets ------------------------------------------------------


def test_task131_strings_exist_in_en_ta_hi():
    from app.web.i18n import STRINGS, t_for

    keys = ("live.upload_section", "dash.update_today",
            "composer.lang_aria", "composer.choose_language",
            "composer.too_big", "composer.still_working")
    for lang in ("en", "ta", "hi"):
        for key in keys:
            assert key in STRINGS[lang], (lang, key)
            assert t_for(lang)(key) != key, (lang, key)


def test_seller_pages_render_in_ta_and_hi(tmp_path):
    client, token = _seller_pages(tmp_path)
    urls = [f"/e/{token}", f"/e/{token}/live", f"/e/{token}/update",
            f"/e/{token}/purchases", f"/e/{token}/bills/new",
            f"/e/{token}/photos", f"/e/{token}/settings"]
    for lang in ("ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 200, (lang, url)


def test_js_assets_check_clean():
    node = shutil.which("node")
    assert node, "node is required"
    for path in (COMPOSER_JS, UPLOAD_JS):
        result = subprocess.run([node, "--check", str(path)], check=False,
                                capture_output=True, text=True)
        assert result.returncode == 0, (path, result.stderr)
