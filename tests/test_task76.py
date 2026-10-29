"""Task 76: Inter for English (Latin) text in the UI and PDFs.

Noto Sans Tamil / Devanagari / other Noto fonts keep their scripts;
Plus Jakarta Sans leaves the UI (its file stays for the logo generator).
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.config import load_settings
from app.models import DraftItem, Item, PriceLine, Proof

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "app" / "web" / "static" / "fonts"
CSS = ROOT / "app" / "web" / "static" / "app.css"
SW = ROOT / "app" / "web" / "static" / "sw.js"
DOCS = ROOT / "docs" / "fonts.md"

LATIN_RANGE = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, "
               "U+02DA, U+02DC, U+2000-206F, U+2074, U+20AC, U+20B9, "
               "U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")

# Tamil + Devanagari @font-face blocks must be byte-identical to before.
TAMIL_REGULAR = """@font-face {
  font-family: "Noto Sans Tamil";
  src: url("fonts/NotoSansTamil-Regular.ttf") format("truetype");
  font-display: swap;
  unicode-range: U+0B80-0BFF;
}"""
TAMIL_BOLD = """@font-face {
  font-family: "Noto Sans Tamil";
  font-weight: 700;
  src: url("fonts/NotoSansTamil-Bold.ttf") format("truetype");
  font-display: swap;
  unicode-range: U+0B80-0BFF;
}"""
DEVANAGARI_REGULAR = """@font-face {
  font-family: "Noto Sans Devanagari";
  src: url("fonts/NotoSansDevanagari-Regular.ttf") format("truetype");
  font-display: swap;
  unicode-range: U+0900-097F, U+A830-A83F;
}"""
DEVANAGARI_BOLD = """@font-face {
  font-family: "Noto Sans Devanagari";
  font-weight: 700;
  src: url("fonts/NotoSansDevanagari-Bold.ttf") format("truetype");
  font-display: swap;
  unicode-range: U+0900-097F, U+A830-A83F;
}"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_inter_files_and_license_exist():
    ttf = FONTS_DIR / "InterVariable.ttf"
    woff2 = FONTS_DIR / "InterVariable.woff2"
    license = FONTS_DIR / "Inter-LICENSE.txt"
    assert ttf.is_file() and woff2.is_file() and license.is_file()
    assert ttf.read_bytes()[:4] == b"\x00\x01\x00\x00", "Inter TTF bad magic"
    assert woff2.read_bytes()[:4] == b"wOF2", "Inter WOFF2 bad magic"
    assert 20 * 1024 <= ttf.stat().st_size <= 2 * 1024 * 1024
    assert 20 * 1024 <= woff2.stat().st_size <= 2 * 1024 * 1024
    text = license.read_text()
    assert "SIL Open Font License" in text
    assert "1.1" in text


def test_docs_fonts_records_version_and_hashes():
    assert DOCS.is_file(), "docs/fonts.md missing"
    text = DOCS.read_text()
    assert "4.1" in text, "Inter release version missing"
    assert "rsms/inter" in text
    for filename in ("InterVariable.ttf", "InterVariable.woff2",
                     "Inter-LICENSE.txt"):
        digest = _sha256(FONTS_DIR / filename)
        assert digest in text, f"{filename} sha256 not in docs/fonts.md"


def _font_face_blocks(css: str) -> list[str]:
    return re.findall(r"@font-face\s*\{[^}]+\}", css, re.DOTALL)


def test_css_inter_first_for_latin():
    css = CSS.read_text()
    inter = [b for b in _font_face_blocks(css) if '"Inter"' in b]
    assert len(inter) == 1, "want exactly one Inter @font-face"
    block = inter[0]
    assert "font-display" in block and "swap" in block
    assert "InterVariable.woff2" in block
    assert "InterVariable.ttf" in block
    assert re.sub(r"\s+", " ", block).find(
        re.sub(r"\s+", " ", LATIN_RANGE)) != -1, "Latin unicode-range changed"
    no_faces = re.sub(r"@font-face\s*\{[^}]+\}", "", css, flags=re.DOTALL)
    stacks = re.findall(r"font-family\s*:\s*([^;]+);", no_faces)
    assert stacks
    for stack in stacks:
        first = stack.strip().split(",")[0].strip().strip("'\"")
        assert first != "Plus Jakarta Sans", f"Jakarta-led stack: {stack}"
    latin_stacks = [s for s in stacks if "Noto Sans Tamil" in s]
    assert latin_stacks, "no UI font stack found"
    for stack in latin_stacks:
        first = stack.strip().split(",")[0].strip().strip("'\"")
        assert first == "Inter", f"Inter must lead: {stack}"
    assert "Plus Jakarta Sans" not in css
    assert "PlusJakartaSans" not in css


def test_css_tamil_hindi_faces_unchanged():
    css = CSS.read_text()
    for block in (TAMIL_REGULAR, TAMIL_BOLD,
                  DEVANAGARI_REGULAR, DEVANAGARI_BOLD):
        assert block in css, f"changed or missing block:\n{block}"


def test_css_tabular_numbers_and_heading_tuning():
    css = CSS.read_text()
    assert re.search(r'font-feature-settings\s*:\s*"tnum"\s*1', css), \
        "tnum missing for prices/totals/tables"
    assert re.search(r"h1\s*\{[^}]*letter-spacing\s*:\s*-0\.02em", css), \
        "h1 needs -0.02em letter-spacing"


def test_jakarta_file_kept_for_logo_generator():
    # Task 95: the logo generator now sets the wordmark in Inter 800; the
    # Jakarta file stays on disk but is no longer referenced by it.
    assert (FONTS_DIR / "PlusJakartaSans-Variable.ttf").is_file()
    logo_py = ROOT / "scripts" / "make_brand_assets.py"
    assert "InterVariable.ttf" in logo_py.read_text()
    assert "PlusJakartaSans-Variable.ttf" not in logo_py.read_text()


def test_service_worker_caches_inter():
    text = SW.read_text()
    assert "InterVariable.woff2" in text
    assert "InterVariable.ttf" in text
    assert "PlusJakartaSans" not in text


def _pdf_font_names(pdf: bytes) -> list[str]:
    from pypdf import PdfReader

    names: list[str] = []
    for page in PdfReader(io.BytesIO(pdf)).pages:
        fonts = ((page.get("/Resources") or {}).get("/Font") or {})
        try:
            items = fonts.items()
        except AttributeError:
            continue
        for _key, ref in items:
            try:
                obj = ref.get_object()
            except Exception:  # noqa: BLE001, S112 - skip unreadable ref
                continue
            for pdf_key in ("/BaseFont", "/FontName"):
                if pdf_key in obj:
                    names.append(str(obj[pdf_key]))
    return names


def _board_pdf(name_local: str, lang: str) -> bytes:
    from app.models import Item
    from app.outputs.pdf import price_board_pdf

    shop = {"name": "T76 Store", "slug": "t76-store", "area": "Koyambedu",
            "phone": "+914400000076", "currency": "INR"}
    items = [Item(
        id=1, version_id=1, name_local=name_local, name_en="tomato",
        variety=None, qty=None, qty_unit=None, photo=None, sold_out=False,
        price_lines=[PriceLine(Decimal(40), Decimal(1), "kg", "")],
        proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0))]
    return price_board_pdf(shop, items, datetime(2026, 10, 29, 9, 0),
                           "http://127.0.0.1:8000/s/t76-store", lang=lang)


def test_price_board_embeds_inter_and_tamil():
    pdf = _board_pdf("தக்காளி", "ta")
    assert pdf[:5] == b"%PDF-"
    names = _pdf_font_names(pdf)
    assert names, "no embedded font names"
    assert any("Inter" in name for name in names), f"Inter missing: {names}"
    assert any("Tamil" in name for name in names), f"Tamil missing: {names}"


def test_price_board_hindi_embeds_devanagari():
    pdf = _board_pdf("टमाटर", "hi")
    names = _pdf_font_names(pdf)
    assert any("Inter" in name for name in names), f"Inter missing: {names}"
    assert any("Devanagari" in name for name in names), \
        f"Devanagari missing: {names}"


def test_all_pdfs_render_all_langs():
    from app.outputs.bill_pdf import bill_pdf
    from app.outputs.day_pdf import day_summary_pdf
    from app.outputs.link_card import link_card_pdf
    from app.outputs.pdf import price_tags_pdf
    from app.outputs.quote_pdf import quote_pdf

    shop = {"name": "T76 Store", "slug": "t76-store", "area": "Koyambedu",
            "phone": "+914400000076", "currency": "INR"}
    lines = [{"name_en": "tomato", "name_local": "தக்காளி", "qty": "2",
              "unit": "kg", "unit_price": "40", "per_amount": "1",
              "line_total": "80", "status": "priced"}]
    tiles = {"sales_fmt": "₹120", "bills_count": 2, "cash_fmt": "₹100",
             "upi_fmt": "₹20", "card_fmt": "₹0", "unpaid_fmt": "₹0",
             "spent_fmt": "₹40", "margin_fmt": "₹80"}
    day_items = [{"display": "tomato", "name_local": "தக்காளி",
                  "sold": "2 kg", "amount": "80",
                  "opening": "5 kg", "left": "3 kg"}]
    at = datetime(2026, 10, 29, 9, 0)
    url = "http://127.0.0.1:8000/s/t76-store"
    for lang in ("en", "ta", "hi"):
        pdfs = [
            ("board", _board_pdf("தக்காளி", lang)),
            ("tags", price_tags_pdf(
                shop, [Item(
                    id=1, version_id=1, name_local="தக்காளி",
                    name_en="tomato", variety=None, qty=None, qty_unit=None,
                    photo=None, sold_out=False,
                    price_lines=[PriceLine(Decimal(40), Decimal(1), "kg",
                                           "")],
                    proof=Proof(quote="", turn_ids=[], start_ms=0,
                                end_ms=0))], at, url, lang=lang)),
            ("bill", bill_pdf(shop, 76, lines, "80", "29 Oct 2026",
                              lang=lang)),
            ("close", day_summary_pdf(shop, "29 Oct 2026", tiles, day_items,
                                      lang=lang)),
            ("link", link_card_pdf(shop, "http://127.0.0.1:8000/e/tok",
                                   lang=lang)),
        ]
        for name, pdf in pdfs:
            assert pdf[:5] == b"%PDF-", f"{lang} {name} not a pdf"
            names = _pdf_font_names(pdf)
            assert any("Inter" in n for n in names), \
                f"{lang} {name} missing Inter: {names}"
    quote = quote_pdf(shop, lines, "80", "prices of today", url + "/q/abc")
    assert quote[:5] == b"%PDF-"
    assert any("Inter" in n for n in _pdf_font_names(quote))


def _client(tmp_path):
    from app.web.main import create_app

    env = {"MODEL_API_KEY": "k", "DATA_DIR": str(tmp_path / "data")}
    return TestClient(create_app(load_settings(env)), follow_redirects=False)


def _create_shop(client):
    resp = client.post("/new", data={
        "name": "T76 Store", "phone": "+914400000076", "area": "Koyambedu",
        "language": "ta", "currency": "INR", "type": "vegetable"})
    assert resp.status_code in (302, 303)
    return resp.headers["location"].split("/e/")[1]


def _seed(tmp_path, token):
    from app.market.quote import Quote, QuoteLine

    conn = db.connect(tmp_path / "data")
    try:
        shop = db.shop_by_token(conn, token)
        session_id = db.create_session(conn, shop["id"], "video")
        drafts = [DraftItem(
            name_spoken="thakkali", name_local="தக்காளி", name_en="tomato",
            variety=None,
            price_lines=[PriceLine(Decimal(40), Decimal(1), "kg", "")],
            qty=None, qty_unit=None,
            proof=Proof(quote="", turn_ids=[], start_ms=0, end_ms=0),
            confirmed=True)]
        version_id = db.approve(conn, session_id, drafts)
        db.set_published(conn, version_id, True)
        quote = Quote(lines=[QuoteLine(
            name_en="tomato", name_local="தக்காளி", qty=Decimal(1),
            unit="kg", unit_price=Decimal(40), per_amount=Decimal(1),
            line_total=Decimal(40), status="priced")],
            total=Decimal(40), priced_count=1, unpriced_count=0,
            prices_set_at=datetime.now(UTC))
        qtoken = db.create_quote(conn, shop_id=shop["id"], quote=quote,
                                 source="seller", kind="bill",
                                 status="billed")
        bill_id = db.get_quote_by_token(conn, qtoken)["id"]
        review_id = db.create_session(conn, shop["id"], "video")
        db.set_session_status(conn, review_id, "review", "waiting")
        return shop["slug"], version_id, bill_id, review_id
    finally:
        conn.close()


def test_every_page_renders_all_langs(tmp_path):
    client = _client(tmp_path)
    token = _create_shop(client)
    slug, version_id, bill_id, review_id = _seed(tmp_path, token)
    pages = ["/", f"/e/{token}", f"/s/{slug}", f"/e/{token}/live",
             f"/e/{token}/s/{review_id}", f"/e/{token}/bills",
             f"/e/{token}/bills/new", f"/e/{token}/bills/{bill_id}",
             f"/e/{token}/close", f"/e/{token}/settings",
             f"/e/{token}/purchases"]
    pdfs = [f"/e/{token}/v/{version_id}/board.pdf", f"/e/{token}/tags.pdf",
            f"/e/{token}/close.pdf"]
    for lang in ("en", "ta", "hi"):
        client.cookies.set("ui_lang", lang)
        for url in pages:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url} -> {resp.status_code}"
            if lang != "en":
                assert any(ord(c) > 127 for c in resp.text), \
                    f"{lang} {url} has no translated script"
        for url in pdfs:
            resp = client.get(url)
            assert resp.status_code == 200, f"{lang} {url} -> {resp.status_code}"
            assert resp.content[:5] == b"%PDF-", f"{lang} {url} not a pdf"
    client.cookies.set("ui_lang", "en")
