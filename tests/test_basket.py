"""Task 17: budget basket with checked explanation."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.market.basket import explain_basket, plan_basket
from app.market.search import Listing, Query, Want
from app.models import DraftItem, PriceLine, Proof
from app.pipeline.names import CANONICAL_NAMES
from app.pipeline.units import rate
from app.web.main import create_app


def make_listing(shop_name, name_en, price, per_amount=1, unit="kg",
                 stale=False, slug=None, variety=None):
    line = PriceLine(Decimal(price), Decimal(per_amount), unit)
    computed = rate(line)
    return Listing(
        shop_name=shop_name,
        slug=slug or shop_name.lower().replace(" ", "-"),
        area="Koyambedu",
        is_demo=False,
        name_en=name_en,
        variety=variety,
        line=line,
        rate=computed[0] if computed else None,
        rate_unit=computed[1] if computed else None,
        updated_at=datetime.now(UTC),
        stale=stale,
    )


def test_split_cheapest_per_item():
    wants = [Want("tomato", None, None, None),
             Want("onion", None, None, None)]
    listings = [
        make_listing("A", "tomato", 18),
        make_listing("B", "tomato", 22),
        make_listing("B", "onion", 30),
        make_listing("A", "onion", 25),
    ]
    plans = plan_basket(wants, listings, Decimal(300))
    split = next(p for p in plans if p.kind == "split")
    assert split.total == Decimal(43)
    assert isinstance(split.total, Decimal)
    by_want = {line.want.name_en: line for line in split.lines}
    assert by_want["tomato"].listing.shop_name == "A"
    assert by_want["onion"].listing.shop_name == "A"
    assert by_want["tomato"].cost == Decimal(18)
    assert by_want["onion"].cost == Decimal(25)
    assert split.missing == []


def test_single_shop_needs_all_items():
    wants = [Want("tomato", None, None, None),
             Want("potato", None, None, None)]
    listings = [
        make_listing("A", "tomato", 18),
        make_listing("B", "tomato", 22),
        make_listing("B", "potato", 30),
    ]
    plans = plan_basket(wants, listings, None)
    single = [p for p in plans if p.kind == "single_shop"]
    assert len(single) == 1
    assert single[0].shop == "B"
    assert single[0].total == Decimal(52)
    assert single[0].missing == []


def test_single_shop_omitted_when_none_has_all():
    wants = [Want("tomato", None, None, None),
             Want("potato", None, None, None)]
    listings = [
        make_listing("A", "tomato", 18),
        make_listing("B", "potato", 30),
    ]
    plans = plan_basket(wants, listings, None)
    assert [p.kind for p in plans] == ["split"]


def test_missing_amount_assumed():
    plans = plan_basket([Want("tomato", None, None, None)],
                        [make_listing("A", "tomato", 18)], None)
    assert plans[0].lines[0].assumed is True
    assert plans[0].lines[0].cost == Decimal(18)


def test_explicit_amount_scales_cost():
    wants = [Want("tomato", Decimal(2), "kg", None)]
    plans = plan_basket(wants, [make_listing("A", "tomato", 18)], None)
    assert plans[0].lines[0].assumed is False
    assert plans[0].lines[0].cost == Decimal(36)


def test_costs_round_to_nearest_half_rupee():
    # 10 for 300 g, want 100 g -> 3.333... -> 3.5
    wants = [Want("tomato", Decimal(100), "g", None)]
    listings = [make_listing("A", "tomato", 10, 300, "g")]
    plans = plan_basket(wants, listings, None)
    assert plans[0].lines[0].cost == Decimal("3.5")
    assert plans[0].total == Decimal("3.5")


def test_stale_ignored():
    wants = [Want("tomato", None, None, None)]
    listings = [
        make_listing("A", "tomato", 10, stale=True),
        make_listing("B", "tomato", 22, stale=False),
    ]
    plans = plan_basket(wants, listings, None)
    split = plans[0]
    assert split.lines[0].listing.shop_name == "B"
    assert split.lines[0].cost == Decimal(22)


def test_missing_want_listed_when_no_fresh_listing():
    wants = [Want("tomato", None, None, None),
             Want("potato", None, None, None)]
    listings = [make_listing("A", "tomato", 18)]
    plans = plan_basket(wants, listings, None)
    split = next(p for p in plans if p.kind == "split")
    assert split.missing == ["potato"]
    assert [line.want.name_en for line in split.lines] == ["tomato"]


def test_all_stale_means_everything_missing():
    wants = [Want("tomato", None, None, None)]
    listings = [make_listing("A", "tomato", 10, stale=True)]
    plans = plan_basket(wants, listings, None)
    assert plans[0].lines == []
    assert plans[0].missing == ["tomato"]
    assert plans[0].total == Decimal(0)


def _ledger_and_settings(tmp_path):
    ledger = CostLedger(tmp_path / "c.db", 100.0)
    settings = load_settings({"MODEL_API_KEY": "k"})
    return ledger, settings


def _two_shop_plans():
    wants = [Want("tomato", None, None, None),
             Want("onion", None, None, None)]
    listings = [
        make_listing("A", "tomato", 18),
        make_listing("B", "tomato", 22),
        make_listing("B", "onion", 30),
        make_listing("A", "onion", 25),
    ]
    return plan_basket(wants, listings, Decimal(300))


def test_explanation_with_foreign_number_falls_back(monkeypatch, tmp_path):
    def fake_chat_json(messages, **kwargs):
        return {"explanation": "All yours for just ₹999 today!"}

    monkeypatch.setattr("app.market.basket.chat_json", fake_chat_json)
    ledger, settings = _ledger_and_settings(tmp_path)
    text = explain_basket(_two_shop_plans(), Decimal(300),
                          ledger=ledger, settings=settings)
    assert "999" not in text
    assert "43" in text


def test_explanation_uses_low_reasoning_effort(monkeypatch, tmp_path):
    seen = {}

    def fake_chat_json(messages, **kwargs):
        seen.update(kwargs)
        return {"explanation": "Split costs ₹43."}

    monkeypatch.setattr("app.market.basket.chat_json", fake_chat_json)
    ledger, settings = _ledger_and_settings(tmp_path)
    explain_basket(_two_shop_plans(), Decimal(300),
                   ledger=ledger, settings=settings)
    assert seen.get("reasoning_effort") == "low"


def test_explanation_passes_through_when_numbers_match(monkeypatch, tmp_path):
    def fake_chat_json(messages, **kwargs):
        return {"explanation": "Split costs ₹43 within your ₹300 budget."}

    monkeypatch.setattr("app.market.basket.chat_json", fake_chat_json)
    ledger, settings = _ledger_and_settings(tmp_path)
    text = explain_basket(_two_shop_plans(), Decimal(300),
                          ledger=ledger, settings=settings)
    assert text == "Split costs ₹43 within your ₹300 budget."


# --- /market budget page ---

def draft(name_en, price, per_amount=1, unit="kg"):
    return DraftItem(
        name_spoken=name_en,
        name_ta=CANONICAL_NAMES[name_en],
        name_en=name_en,
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(per_amount), unit)],
        qty=None,
        qty_unit=None,
        proof=Proof(quote="q", turn_ids=[1], start_ms=0, end_ms=1000),
    )


def make_shop(conn, name, **kwargs):
    params = {"phone": "+914400000000", "area": "Koyambedu",
              "language": "ta", "currency": "INR", "shop_type": "vegetable",
              "listed": True}
    params.update(kwargs)
    return db.create_shop(conn, name=name, **params)


def publish(conn, shop_id, drafts):
    session_id = db.create_session(conn, shop_id, "video")
    version_id = db.approve(conn, session_id, drafts)
    db.set_published(conn, version_id, True)
    return version_id


def test_market_budget_shows_plans_assumptions_and_explanation(tmp_path,
                                                              monkeypatch):
    conn = db.connect(tmp_path / "data")
    try:
        a_id, _, _ = make_shop(conn, "Shop A")
        b_id, _, _ = make_shop(conn, "Shop B")
        publish(conn, a_id, [draft("tomato", 18), draft("onion", 25)])
        publish(conn, b_id, [draft("tomato", 22), draft("onion", 30)])
    finally:
        conn.close()

    def fake_parse_query(text, **kwargs):
        return Query([Want("tomato", None, None, None),
                      Want("onion", None, None, None)],
                     Decimal(300), None)

    def fake_explain(plans, budget, **kwargs):
        return "Fresh picks within budget."

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    monkeypatch.setattr("app.web.main.explain_basket", fake_explain)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    html = client.get("/market", params={"q": "300 for tomato onion"}).text
    assert "₹43" in html
    assert "(assumed 1 kg)" in html
    assert "Fresh picks within budget." in html


def test_market_budget_names_missing_want(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "data")
    try:
        a_id, _, _ = make_shop(conn, "Shop A")
        publish(conn, a_id, [draft("tomato", 18)])
    finally:
        conn.close()

    def fake_parse_query(text, **kwargs):
        return Query([Want("tomato", None, None, None),
                      Want("potato", None, None, None)],
                     Decimal(300), None)

    def fake_explain(plans, budget, **kwargs):
        return "One item missing."

    monkeypatch.setattr("app.web.main.parse_query", fake_parse_query)
    monkeypatch.setattr("app.web.main.explain_basket", fake_explain)
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    client = TestClient(create_app(settings))
    html = client.get("/market", params={"q": "300 for tomato potato"}).text
    assert "potato" in html
    assert "No fresh prices for" in html
