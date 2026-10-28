"""Task 25: photo_checks table and item stock columns."""

import json
import sqlite3

import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path)
    yield connection
    connection.close()


def make_shop(conn, name="Kannan Store"):
    return db.create_shop(conn, name=name, phone="+914400000000", area="Koyambedu",
                          language="ta", currency="INR", shop_type="vegetable")


def test_photo_checks_round_trip(conn):
    shop_id, _, _ = make_shop(conn)
    report = {"products": [{"name_en": "tomato", "count": 12}],
              "quality": "good", "suggestions": []}
    check_id = db.save_photo_check(conn, shop_id=shop_id, image_path="photos/p1.jpg",
                                   report_json=report, cost=0.0125)
    assert check_id
    rows = db.load_photo_checks(conn, shop_id)
    assert len(rows) == 1
    assert rows[0]["id"] == check_id
    assert rows[0]["image_path"] == "photos/p1.jpg"
    assert json.loads(rows[0]["report_json"]) == report
    assert rows[0]["cost"] == pytest.approx(0.0125)
    assert rows[0]["created_at"]


def test_photo_checks_accepts_json_string(conn):
    shop_id, _, _ = make_shop(conn)
    db.save_photo_check(conn, shop_id=shop_id, image_path="p.jpg",
                        report_json='{"quality": "good"}', cost=0.01)
    (row,) = db.load_photo_checks(conn, shop_id)
    assert json.loads(row["report_json"]) == {"quality": "good"}


def test_set_stock_on_fresh_db(conn):
    shop_id, _, _ = make_shop(conn)
    session_id = db.create_session(conn, shop_id, "video")
    from tests.test_db import make_draft

    version_id = db.approve(conn, session_id, [make_draft()])
    (item,) = db.version_items(conn, version_id)
    db.set_stock(conn, item.id, 24, "piece", "photo")
    row = conn.execute("SELECT stock_qty, stock_unit, stock_source FROM items"
                       " WHERE id = ?", (item.id,)).fetchone()
    assert (row["stock_qty"], row["stock_unit"], row["stock_source"]) == (
        "24", "piece", "photo")


def test_set_stock_migrates_old_db(tmp_path):
    old_path = tmp_path / "marketmate.db"
    old = sqlite3.connect(old_path)
    old.execute(
        "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " version_id INTEGER NOT NULL REFERENCES versions(id),"
        " name_ta TEXT NOT NULL, name_en TEXT NOT NULL, variety TEXT,"
        " qty TEXT, qty_unit TEXT, photo TEXT,"
        " sold_out INTEGER NOT NULL DEFAULT 0, proof TEXT NOT NULL)")
    old.commit()
    old.close()
    conn = db.connect(tmp_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
        assert {"stock_qty", "stock_unit", "stock_source"} <= columns
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'photo_checks'"
        ).fetchone() is not None
        shop_id, _, _ = make_shop(conn)
        version_id = conn.execute(
            "INSERT INTO versions (shop_id, created_at, published)"
            " VALUES (?, '2026-10-28T00:00:00+00:00', 0)",
            (shop_id,)).lastrowid
        item_id = conn.execute(
            "INSERT INTO items (version_id, name_ta, name_en, proof)"
            " VALUES (?, 'x', 'tomato', '{}')", (version_id,)).lastrowid
        conn.commit()
        db.set_stock(conn, item_id, 31, "piece", "photo")
        row = conn.execute("SELECT stock_qty, stock_unit, stock_source FROM items"
                           " WHERE id = ?", (item_id,)).fetchone()
        assert (row["stock_qty"], row["stock_unit"], row["stock_source"]) == (
            "31", "piece", "photo")
    finally:
        conn.close()
