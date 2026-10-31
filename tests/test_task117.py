"""Task 117: five sample shops inside the v11 design.

Merge collateral for tasks 115 + 116: seeded sample shops render
with stall covers, the translated Sample label and the test-order
notice on the homepage, /market and /s/<slug> — with no
"said today HH:MM" and no phone/UPI anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from scripts import seed_samples

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA = ROOT / "scripts" / "sample_data"

# Task 122: v12 marketplace sections.
# Task 127: v13 homepage section order.
SECTIONS = ("hero", "fresh", "cats", "shops", "lowest", "how", "app",
            "markets")
NAMES = ("Selvi Vegetable Stall", "Pandian Fruit Centre",
         "Amma Keerai Kadai", "Gupta Sabzi Wale", "Green Basket")


def make_client(tmp_path, lang="en"):
    from app.web.main import create_app

    client = TestClient(create_app(load_settings(
        {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")})),
        follow_redirects=False)
    client.cookies.set("ui_lang", lang)
    return client


def seed(data_dir):
    return seed_samples.seed(Path(data_dir), SAMPLE_DATA,
                             "http://localhost:8000")


def test_homepage_shows_five_sample_shops_with_covers(tmp_path):
    from app.web.i18n import t_for

    seed(tmp_path / "data")
    html = make_client(tmp_path).get("/").text
    t = t_for("en")
    for name in NAMES:
        assert name in html, name
    assert t("hp.demo") in html
    assert t("hp.said_sample") in html
    assert re.search(r"said today \d\d:\d\d", html) is None
    for section in SECTIONS:
        assert f'id="{section}"' in html, section
    for slug in seed_samples.SLUGS:
        assert f"/m/{slug}.jpg" in html, slug


def test_market_rows_show_sample_label_and_cover(tmp_path, monkeypatch):
    from decimal import Decimal

    from app.market.search import Query, Want
    from app.web.i18n import t_for

    seed(tmp_path / "data")
    client = make_client(tmp_path)
    monkeypatch.setattr(
        "app.web.main.parse_query",
        lambda text, **_kw: Query(
            [Want("tomato", Decimal(1), "kg", None)], None, None))
    monkeypatch.setattr("app.web.main.explain_basket",
                        lambda plans, budget, **_kw: "Basket picks.")
    html = client.get("/market?q=tomato").text
    assert t_for("en")("hp.demo") in html
    assert "Demo data" not in html
    assert "/m/" in html
    assert "data-shop-row" in html


def test_shop_page_shows_cover_label_and_notice(tmp_path):
    from app.web.i18n import t_for

    seed(tmp_path / "data")
    html = make_client(tmp_path).get("/s/selvi-vegetable-stall").text
    t = t_for("en")
    assert "/m/selvi-vegetable-stall.jpg" in html
    assert t("hp.demo") in html
    assert "Demo data" not in html
    assert "data-sample-notice" in html
    assert t("order.sample_notice") in html
    assert "tel:" not in html
    assert "upi" not in html.lower().replace("sample", "")
