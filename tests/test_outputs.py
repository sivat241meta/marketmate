import csv
import io
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import Item, PriceLine, Proof
from app.outputs.csv_export import generic_csv, posapp_pos_csv
from app.outputs.pdf import price_board_pdf
from app.outputs.qr import qr_png
from app.outputs.value import stock_value
from app.web.main import create_app

IST = ZoneInfo("Asia/Kolkata")


def pl(price, per_amount, unit, said=""):
    return PriceLine(
        Decimal(price) if price is not None else None,
        Decimal(per_amount) if per_amount is not None else None,
        unit,
        said,
    )


def item(name_en="tomato", name_ta="தக்காளி", variety=None, qty=None,
         qty_unit=None, lines=()):
    return Item(
        id=1, version_id=1, name_ta=name_ta, name_en=name_en, variety=variety,
        qty=Decimal(qty) if qty is not None else None, qty_unit=qty_unit,
        photo=None, sold_out=False, price_lines=list(lines),
        proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0),
    )


def demo_shop_row():
    return {
        "name": "Demo Stall", "slug": "demo-stall", "area": "Koyambedu",
        "phone": "+914400000000",
    }


def test_value_example():
    goods = [item(qty=40, qty_unit="kg", lines=[pl(18, 1, "kg")])]
    assert stock_value(goods)[0] == 720


def test_value_quarter_kilo_line():
    goods = [item(qty=2, qty_unit="kg", lines=[pl(15, 250, "g")])]
    assert stock_value(goods)[0] == 120


def test_value_lists_missing():
    goods = [item(qty=None, lines=[pl(18, 1, "kg")])]
    total, left_out = stock_value(goods)
    assert total == 0
    assert left_out == ["tomato"]


def test_value_lists_unconvertible_unit():
    goods = [item(qty=3, qty_unit="kg", lines=[pl(60, 1, "dozen")])]
    total, left_out = stock_value(goods)
    assert total == 0
    assert left_out == ["tomato"]


def test_generic_csv_rows_per_line():
    goods = [item(variety="bengaluru", qty=40, qty_unit="kg",
                  lines=[pl(18, 1, "kg"), pl(20, 1, "kg")])]
    rows = list(csv.reader(io.StringIO(generic_csv(
        goods, datetime(2026, 10, 28, 9, 0, tzinfo=IST)))))
    assert rows[0] == ["name_en", "name_ta", "variety", "price", "per_amount",
                       "unit", "qty", "qty_unit", "updated_at"]
    assert len(rows) == 3
    assert rows[1][:8] == ["tomato", "தக்காளி", "bengaluru", "18", "1",
                           "kg", "40", "kg"]
    assert rows[2][3:6] == ["20", "1", "kg"]


def test_posapp_csv_first_line_only():
    goods = [item(variety="bengaluru",
                  lines=[pl(18, 1, "kg"), pl(20, 1, "kg")])]
    rows = list(csv.reader(io.StringIO(posapp_pos_csv(goods))))
    assert rows[0] == ["Item Name", "Selling Price", "Unit", "Description"]
    assert rows[1] == ["Tomato (Bengaluru)", "18", "kg", "தக்காளி"]
    assert len(rows) == 2


def test_qr_png_bytes():
    data = qr_png("http://127.0.0.1:8000/s/demo-stall")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def pypdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_has_prices_and_shop():
    pdf = price_board_pdf(
        demo_shop_row(),
        [item(variety="bengaluru", lines=[pl(18, 1, "kg")])],
        datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/demo-stall",
    )
    assert pdf[:5] == b"%PDF-"
    text = pypdf_text(pdf)
    assert "₹18" in text and "Demo Stall" in text


def test_pdf_plain_price_figures():
    pdf = price_board_pdf(
        demo_shop_row(),
        [item(name_en="banana", name_ta="வாழைப்பழம்",
              lines=[pl(60, 1, "dozen")])],
        datetime(2026, 10, 28, 9, 0, tzinfo=IST),
        "http://127.0.0.1:8000/s/demo-stall",
    )
    assert "₹60" in pypdf_text(pdf)


def seed_version(tmp_path):
    from app.models import DraftItem

    data_dir = tmp_path / "data"
    conn = db.connect(data_dir)
    try:
        shop_id, _, token = db.create_shop(
            conn, name="Demo Stall", phone="+914400000000", area="Koyambedu",
            language="ta", currency="INR", shop_type="vegetable")
        session_id = db.create_session(conn, shop_id, "video")
        draft = DraftItem(
            name_spoken="tomato", name_ta="தக்காளி", name_en="tomato",
            variety="bengaluru", price_lines=[pl(18, 1, "kg", "kilo eighteen")],
            qty=Decimal(40), qty_unit="kg",
            proof=Proof(quote="tomato", turn_ids=[], start_ms=0, end_ms=0),
            confirmed=True,
        )
        version_id = db.approve(conn, session_id, [draft])
        return token, version_id
    finally:
        conn.close()


def output_client(tmp_path, monkeypatch):
    settings = load_settings({"MODEL_API_KEY": "k",
                              "DATA_DIR": str(tmp_path / "data")})
    return TestClient(create_app(settings), follow_redirects=False)


def test_output_routes(tmp_path, monkeypatch):
    client = output_client(tmp_path, monkeypatch)
    token, version_id = seed_version(tmp_path)
    base = f"/e/{token}/v/{version_id}"
    pdf = client.get(base + "/board.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-"
    csv_resp = client.get(base + "/export.csv")
    assert csv_resp.status_code == 200
    assert "name_en,name_ta" in csv_resp.text
    posapp = client.get(base + "/posapp.csv")
    assert posapp.status_code == 200
    assert "Item Name" in posapp.text
    assert client.get(f"/e/{token}/v/9999/board.pdf").status_code == 404


def test_seller_home_shows_stock_value(tmp_path, monkeypatch):
    client = output_client(tmp_path, monkeypatch)
    token, _ = seed_version(tmp_path)
    html = client.get(f"/e/{token}").text
    assert "₹720" in html
