"""Task 79: real-world object icons (Fluent Emoji Flat, MIT).

Object icons (ui.obj) for nav, action buttons, stat squares and empty
states; line icons (ui.icon) stay for small controls. Every object icon
has a visible text label next to or under it, and the WhatsApp logo is
never used (WhatsApp buttons use the speech balloon).
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from test_task64 import BILL_HOOKS, BILLS_NEW_HOOKS, LIVE_HOOKS, REVIEW_HOOKS, SHOP_HOOKS

from app import db
from app.config import load_settings
from app.models import DraftItem, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "app" / "web" / "static" / "icons" / "fluent"
TEMPLATES = ROOT / "app" / "web" / "templates"
SW = ROOT / "app" / "web" / "static" / "sw.js"
DOCS = ROOT / "docs" / "icons.md"

ALLOWED_SIZES = {"20", "24", "26", "28", "56"}


def _referenced_icons() -> set[str]:
    names: set[str] = set()
    for path in TEMPLATES.glob("*.html"):
        if path.name == "_ui.html":
            continue
        text = path.read_text()
        names.update(re.findall(r'ui\.obj\("([a-z_]+)"', text))
    return names


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fluent_files_exist_valid_svg_and_documented():
    names = _referenced_icons()
    assert len(names) >= 25, f"too few object icons: {sorted(names)}"
    assert DOCS.is_file(), "docs/icons.md missing"
    docs = DOCS.read_text()
    assert "fluentui-emoji" in docs
    assert "MIT" in docs
    for name in sorted(names):
        path = ICONS_DIR / f"{name}.svg"
        assert path.is_file(), f"{name}.svg missing"
        data = path.read_bytes()
        assert 100 <= len(data) <= 20 * 1024, f"{name}.svg size {len(data)}"
        root = ET.fromstring(data)
        assert root.tag == "{http://www.w3.org/2000/svg}svg", \
            f"{name}.svg is not an SVG"
        assert f"{name}.svg" in docs, f"{name}.svg not in docs/icons.md"
        digest = _sha256(path)
        assert digest in docs, f"{name}.svg sha256 not in docs/icons.md"
        assert re.search(
            r"https://raw\.githubusercontent\.com/microsoft/fluentui-emoji"
            r"/main/assets/[^ ]*\.svg", docs), "source URL missing"


def test_license_exists_and_is_mit():
    license = ICONS_DIR / "LICENSE"
    assert license.is_file(), "fluent LICENSE missing"
    text = license.read_text()
    assert "MIT License" in text
    assert "Microsoft Corporation" in text


def test_service_worker_caches_icons():
    text = SW.read_text()
    for name in sorted(_referenced_icons()):
        assert f"/static/icons/fluent/{name}.svg" in text, \
            f"{name}.svg not in the service worker cache list"


def test_no_whatsapp_logo():
    static = ROOT / "app" / "web" / "static"
    hits = [p for p in static.rglob("*")
            if "whatsapp" in p.name.lower()]
    assert hits == [], f"WhatsApp logo file present: {hits}"
    for path in TEMPLATES.glob("*.html"):
        if path.name == "_ui.html":
            continue
        assert 'ui.obj("whatsapp"' not in path.read_text(), path.name
    for path in ICONS_DIR.glob("*.svg"):
        assert "whatsapp" not in path.read_text().lower(), path.name


def test_readme_credits_fluent_emoji():
    readme = (ROOT / "README.md").read_text()
    assert "Icons: Fluent Emoji (Flat) by Microsoft, MIT licence." in readme


def _client(tmp_path) -> TestClient:
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client, name="T79 Store", phone="+914400000079",
                 language="ta"):
    resp = client.post("/new", data={
        "name": name, "phone": phone, "area": "Koyambedu",
        "language": language, "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303), resp.text
    return resp.headers["location"].split("/e/")[1]


def _draft(name_en, price, local=None):
    from app.pipeline.names import CANONICAL_NAMES

    return DraftItem(
        name_spoken=name_en,
        name_local=local or CANONICAL_NAMES.get(name_en, name_en),
        name_en=name_en, variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg")],
        qty=None, qty_unit=None,
        proof=Proof(quote=f"{name_en} {price}", turn_ids=[], start_ms=0,
                    end_ms=0),
        flags=[], confirmed=True)


def _publish(tmp_path, token, drafts) -> None:
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
    finally:
        conn.close()


def _seed_bill(tmp_path, token):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        quote = Quote(lines=[QuoteLine(
            name_en="tomato", name_local="தக்காளி", qty=Decimal(1),
            unit="kg", unit_price=Decimal(40), per_amount=Decimal(1),
            line_total=Decimal(40), status="priced")],
            total=Decimal(40), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill",
                                 status="billed")
        return db.get_quote_by_token(conn, qtoken)["id"]
    finally:
        conn.close()


def _slug(tmp_path, token) -> str:
    conn = db.connect(tmp_path / "data")
    try:
        return db.shop_by_token(conn, token)["slug"]
    finally:
        conn.close()


def test_rail_and_bnav_render_object_icons_with_labels(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    html = client.get(f"/e/{token}").text
    rail = re.search(r'<nav class="rail".*?</nav>', html,
                     re.DOTALL).group(0)
    for name, label in (("house", "Today"), ("mic", "Prices"),
                        ("bags", "Orders"), ("receipt", "Bills"),
                        ("ledger", "Credit"), ("moon", "Close")):
        assert f"/static/icons/fluent/{name}.svg" in rail, \
            f"rail missing {name}"
        assert label in rail, f"rail missing {label}"
    assert "More" in rail, "rail missing More"
    assert re.search(r'<a class="ic[^"]*" href="/e/[^"]+#more">'
                     r'<svg class="icon"', rail), \
        "More should keep its line icon"
    bar = re.search(r'<nav class="bnav".*?</nav>', html,
                    re.DOTALL).group(0)
    assert len(re.findall(r"<a ", bar)) == 5, "bnav needs 5 links"
    for name in ("house", "receipt", "mic", "bags", "moon"):
        assert f"/static/icons/fluent/{name}.svg" in bar, \
            f"bnav missing {name}"
    for label in ("Today", "Bills", "Live", "Orders", "Close"):
        assert label in bar, f"bnav missing {label}"
    assert 'class="mic-dot"' in bar, "centre mic needs its white circle"


def test_helper_sees_only_allowed_links(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        _, helper = db.create_helper(conn, shop["id"], "Muthu")
    finally:
        conn.close()
    html = client.get(f"/e/{helper}").text
    assert "/static/icons/fluent/house.svg" in html
    for suffix in ("/live", "/close", "/settings", "/photos",
                   "/purchases"):
        assert f"/e/{helper}{suffix}" not in html, suffix


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def test_object_icons_have_labels_and_dimensions(tmp_path):
    client = _client(tmp_path)
    client.cookies.set("ui_lang", "en")
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40, local="தக்காளி")])
    bill_id = _seed_bill(tmp_path, token)
    urls = ["/", f"/e/{token}", f"/s/{slug}", "/market",
            f"/e/{token}/bills", f"/e/{token}/bills/{bill_id}",
            f"/e/{token}/close", f"/e/{token}/credit",
            f"/e/{token}/settings", f"/e/{token}/photos",
            f"/e/{token}/purchases", f"/e/{token}/update"]
    for url in urls:
        html = client.get(url).text
        imgs = re.findall(r'<img class="obj"[^>]*>', html)
        for img in imgs:
            width = re.search(r'width="(\d+)"', img)
            height = re.search(r'height="(\d+)"', img)
            assert width and height, f"{url}: {img} needs dimensions"
            assert width.group(1) == height.group(1), \
                f"{url}: {img} must be square"
            assert width.group(1) in ALLOWED_SIZES, \
                f"{url}: unexpected icon size {img}"
            assert 'alt=""' in img, f"{url}: {img} must stay decorative"
        for tag in ("a", "button"):
            blocks = re.findall(rf"<{tag}\b[^>]*>.*?</{tag}>", html,
                                re.DOTALL)
            for block in blocks:
                if 'class="obj"' not in block:
                    continue
                if (tag == "a" and 'class="circ"' in block.split(">")[0]
                        and 'aria-label="' in block.split(">")[0]):
                    # The Bag pill beside it is the visible label.
                    continue
                assert _strip_tags(block), \
                    f"{url}: icon-only <{tag}>: {block[:120]}"
        circs = re.findall(r'<a class="circ"[^>]*>.*?</a>', html,
                           re.DOTALL)
        for circ in circs:
            if 'class="obj"' in circ:
                assert 'aria-label="' in circ.split(">")[0]


def test_every_page_renders_all_langs(tmp_path):
    from test_task64 import _render_urls, _seed_render_shop

    client, token, slug, ids = _seed_render_shop(tmp_path)
    urls = _render_urls(token, slug, ids)
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in urls:
            resp = client.get(url)
            assert resp.status_code == 200, \
                f"{lang} {url} -> {resp.status_code}"


def test_js_hooks_present_on_key_pages(tmp_path):
    from test_task64 import _seed_bill_and_session

    client = _client(tmp_path)
    token = _create_shop(client)
    slug = _slug(tmp_path, token)
    _publish(tmp_path, token, [_draft("tomato", 40)])
    bill_id, session_id = _seed_bill_and_session(tmp_path, token)
    pages = [(f"/e/{token}/live", LIVE_HOOKS),
             (f"/e/{token}/s/{session_id}", REVIEW_HOOKS),
             (f"/e/{token}/bills/new", BILLS_NEW_HOOKS),
             (f"/e/{token}/bills/{bill_id}", BILL_HOOKS),
             (f"/s/{slug}", SHOP_HOOKS)]
    for url, hooks in pages:
        html = client.get(url).text
        for hook in hooks:
            assert hook in html, f"{url} missing {hook}"
