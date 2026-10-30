"""Task 81: one landing page with real (Unsplash, credited) photos.

Value, who it's for, how it works, customers, built-with-Meta — in
en/ta/hi. The five marketing photos live in app/web/static/landing/
and must never appear in shop/product templates.
"""

from __future__ import annotations

import hashlib
import html as htmlmod
import re
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.config import load_settings

ROOT = Path(__file__).resolve().parent.parent
LANDING = ROOT / "app" / "web" / "static" / "landing"
TEMPLATES = ROOT / "app" / "web" / "templates"
CREDITS = ROOT / "docs" / "photo-credits.md"

PHOTOS = (
    ("hero.jpg", "czt2KF17CtE", "Frédéric Barriol", (1600, 1061)),
    ("seller-phone.jpg", "CBucCjSOuuY", "Ashwini Chaudhary (Monty)",
     (1600, 1246)),
    ("banana-cart.jpg", "GuBFtfzosaY", "Aditya Sethia", (1600, 1164)),
    ("street-market.jpg", "P0lXf8uN75Y", "Abdullah Azeez", (1600, 2844)),
    ("customer-phone.jpg", "iJfM5uaZ1N4", "Emil Widlund", (1600, 2240)),
)

# Task 122: the homepage is the v12 marketplace; sellers/how content
# moved to /sellers and /how.
SECTIONS = ("mind", "top-shops", "shops", "best-prices", "markets",
            "sell", "meta", "install", "footer")


def make_client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)),
                      follow_redirects=False)


def _home(client, lang):
    client.cookies.set("ui_lang", lang)
    resp = client.get("/")
    assert resp.status_code == 200, lang
    return resp.text


# --- 1. photos on disk --------------------------------------------------------


def test_photos_exist_both_sizes_small_and_exif_free():
    assert LANDING.is_dir()
    for name, _pid, _who, size in PHOTOS:
        big = LANDING / name
        small = LANDING / name.replace(".jpg", "-800.jpg")
        assert big.is_file(), name
        assert small.is_file(), small.name
        assert big.stat().st_size <= 350 * 1024, (name, big.stat().st_size)
        for path, width in ((big, 1600), (small, 800)):
            with Image.open(path) as img:
                assert img.size[0] == width, (path.name, img.size)
                assert dict(img.getexif()) == {}, f"{path.name} keeps EXIF"
                assert img.info.get("progressive"), f"{path.name} not progressive"
        with Image.open(big) as img:
            assert img.size == size, (name, img.size)


# --- 2. credits doc -----------------------------------------------------------


def test_photo_credits_list_all_five_with_hashes():
    text = CREDITS.read_text()
    assert "Unsplash License" in text
    for name, pid, who, _size in PHOTOS:
        assert name in text, name
        assert pid in text, pid
        assert who in text, who
        assert f"https://unsplash.com/photos/{pid}" in text, pid
        digest = hashlib.sha256((LANDING / name).read_bytes()).hexdigest()
        assert digest in text, f"{name} hash mismatch"


# --- 3. landing renders in en/ta/hi with every section -----------------------


def test_landing_sections_in_order_all_langs(tmp_path):
    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        html = _home(client, lang)
        positions = []
        for section in SECTIONS:
            needle = f'id="{section}"'
            assert needle in html, (lang, section)
            positions.append(html.index(needle))
        assert positions == sorted(positions), (lang, "section order")


def test_landing_headline_and_honesty_all_langs(tmp_path):
    from app.web.i18n import t_for

    client = make_client(tmp_path)
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        html = htmlmod.unescape(_home(client, lang))
        t = t_for(lang)
        assert t("land.honest") in html, lang
        assert t("land.meta_code") in html, lang
        assert "github.com/sivat241meta/marketmate" in html, lang
        assert t("land.photos_credit") in html, lang
        assert t("land.icons_credit") in html, lang
        sellers = htmlmod.unescape(client.get("/sellers").text)
        assert t("land.hero_a") in sellers, lang
        assert t("land.hero_b") in sellers, lang
        client.cookies.clear()


# --- 4. CTAs point at existing routes -----------------------------------------


def test_landing_ctas_hit_existing_routes(tmp_path):
    client = make_client(tmp_path)
    html = _home(client, "en")
    assert 'href="/new"' in html
    assert 'href="/market"' in html
    assert 'href="/try"' in html
    for route in ("/new", "/market", "/try"):
        resp = client.get(route)
        assert resp.status_code != 404, route


# --- 5. meta section: only model ids that appear in app/ ----------------------


def test_meta_section_model_ids_exist_in_code(tmp_path):
    client = make_client(tmp_path)
    html = _home(client, "en")
    meta = html.split('id="meta"')[1].split('id="install"')[0]
    text = re.sub(r"<[^>]+>", " ", meta)
    # Task 118: compare rendered text, not markup — entities like &#39;
    # (apostrophe) contain digits that are not model ids.
    text = htmlmod.unescape(text)
    app_source = "\n".join(
        path.read_text()
        for path in sorted((ROOT / "app").rglob("*.py")))
    for known in ("muse-voice-transcribe-1.0", "muse-spark-1.3",
                  "sam-3.1", "meta_sam_parser",
                  "meta-models/muse-spark-open-1026"):
        assert known in text, known
        assert known in app_source, known
    chunks = [chunk.strip(".,;:!?()\"'")
              for chunk in re.split(r"\s+", text)
              if any(ch.isdigit() for ch in chunk)]
    assert chunks, "no model ids found in meta section"
    for chunk in chunks:
        assert chunk in app_source, f"{chunk!r} not found in app/"


# --- 6. landing photos never used as product photos ---------------------------


def test_no_shop_template_uses_landing_photos():
    # Task 122: landing photos live on /sellers + /how now, never on
    # product/shop cards.
    allowed = {"sellers.html", "how.html"}
    offenders = [path.name for path in sorted(TEMPLATES.glob("*.html"))
                 if path.name not in allowed
                 and "landing/" in path.read_text()]
    assert offenders == []


# --- 7. images: lazy, sized, srcset -------------------------------------------


def test_landing_images_lazy_sized_with_srcset(tmp_path):
    # Task 122: the five landing photos live on /sellers + /how.
    client = make_client(tmp_path)
    html = client.get("/sellers").text + client.get("/how").text
    imgs = re.findall(r"<img\b[^>]*landing/[^>]*>", html)
    assert len(imgs) == 5, len(imgs)
    for tag in imgs:
        assert 'width="' in tag and 'height="' in tag, tag
        assert "alt=" in tag, tag
        assert "-800.jpg" in tag and " 800w" in tag, tag
        assert ".jpg" in tag and " 1600w" in tag, tag
        if "hero" in tag and "hero-" not in tag.split("srcset")[0]:
            assert 'fetchpriority="high"' in tag, tag
            assert "loading=" not in tag, tag
        else:
            assert 'loading="lazy"' in tag, tag
    assert html.count("/ Unsplash") >= 10  # caption + hover title each
    for _name, _pid, who, _size in PHOTOS:
        assert who in html, who


def test_phone_weight_under_budget():
    phone_bytes = sum(
        (LANDING / name.replace(".jpg", "-800.jpg")).stat().st_size
        for name, _pid, _who, _size in PHOTOS)
    css_bytes = (ROOT / "app" / "web" / "static" / "app.css").stat().st_size
    assert phone_bytes + css_bytes < 1.5 * 1024 * 1024
