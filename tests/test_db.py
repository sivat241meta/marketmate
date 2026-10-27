from decimal import Decimal

import pytest

from app import db
from app.db import ApprovalError
from app.models import DraftItem, Flag, PriceLine, Proof


def make_shop(conn, name="Kannan Store"):
    return db.create_shop(conn, name=name, phone="+914400000000", area="Koyambedu",
                          language="ta", currency="INR", shop_type="vegetable")


def make_draft(price="18.50"):
    return DraftItem(
        name_spoken="thakkali",
        name_ta="தக்காளி",
        name_en="tomato",
        variety=None,
        price_lines=[PriceLine(Decimal(price), Decimal(1), "kg", "kilo pathinettu")],
        qty=Decimal(40),
        qty_unit="kg",
        proof=Proof(quote="thakkali kilo pathinettu", turn_ids=[1],
                    start_ms=0, end_ms=1000),
    )


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path)
    yield connection
    connection.close()


def test_create_and_lookup_shop(conn):
    shop_id, slug, token = make_shop(conn)
    assert shop_id and slug and token
    assert db.shop_by_token(conn, token)["id"] == shop_id
    assert db.shop_by_slug(conn, slug)["slug"] == slug
    assert db.shop_by_token(conn, "wrong-token") is None
    stored = conn.execute("SELECT edit_token_hash FROM shops WHERE id = ?",
                          (shop_id,)).fetchone()[0]
    assert stored != token and len(stored) == 64


def test_drafts_round_trip(conn):
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    item = make_draft()
    item.flags.append(Flag(field="price", code="SOUND_ALIKE",
                           message="18 or 80?", options=["18", "80"]))
    db.save_drafts(conn, session_id, [item])
    (loaded,) = db.load_drafts(conn, session_id)
    assert loaded.price_lines[0].price == Decimal("18.50")
    assert loaded.qty == Decimal(40)
    assert loaded.proof.quote == "thakkali kilo pathinettu"
    assert loaded.flags[0].code == "SOUND_ALIKE"


def test_approve_rejects_unconfirmed_blocking(conn):
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    item = make_draft()
    item.flags.append(Flag(field="price", code="UNIT_MISSING", message="no unit"))
    with pytest.raises(ApprovalError):
        db.approve(conn, session_id, [item])
    priceless = make_draft()
    priceless.price_lines = []
    with pytest.raises(ApprovalError):
        db.approve(conn, session_id, [priceless])


def test_approve_accepts_confirmed(conn):
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    item = make_draft()
    item.flags.append(Flag(field="price", code="UNIT_MISSING", message="no unit"))
    item.confirmed = True
    version_id = db.approve(conn, session_id, [item])
    assert version_id
    (stored,) = db.version_items(conn, version_id)
    assert stored.name_en == "tomato" and stored.name_ta == "தக்காளி"
    assert stored.price_lines[0].price == Decimal("18.50")


def test_publish_switches(conn):
    shop_id, _, _ = make_shop(conn)
    first = db.create_session(conn, shop_id, "video")
    second = db.create_session(conn, shop_id, "video")
    v1 = db.approve(conn, first, [make_draft()])
    v2 = db.approve(conn, second, [make_draft()])
    db.set_published(conn, v1, True)
    assert db.latest_version(conn, shop_id, published_only=True) == v1
    db.set_published(conn, v2, True)
    assert db.latest_version(conn, shop_id, published_only=True) == v2
    assert db.latest_version(conn, shop_id) == v2


def test_last_prices(conn):
    shop_id, _, _ = make_shop(conn)
    first = db.create_session(conn, shop_id, "video")
    db.approve(conn, first, [make_draft(price="18")])
    second = db.create_session(conn, shop_id, "video")
    db.approve(conn, second, [make_draft(price="20")])
    assert db.last_prices(conn, shop_id)["tomato"].price == Decimal(20)
