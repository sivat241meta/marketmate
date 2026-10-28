"""Task 44: Noto fonts for Hindi, Bengali, Telugu, Kannada and Latin (failing first)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "app" / "web" / "static" / "fonts"
CSS = ROOT / "app" / "web" / "static" / "app.css"
SOURCES = FONTS_DIR / "SOURCES.md"
MODAL_APP = ROOT / "modal_app.py"

BASE = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts"

# filename -> (family name, source URL)
EXPECTED_FONTS: dict[str, tuple[str, str]] = {}
for _family, _css in (
    ("NotoSans", "Noto Sans"),
    ("NotoSansTamil", "Noto Sans Tamil"),
    ("NotoSansDevanagari", "Noto Sans Devanagari"),
    ("NotoSansBengali", "Noto Sans Bengali"),
    ("NotoSansTelugu", "Noto Sans Telugu"),
    ("NotoSansKannada", "Noto Sans Kannada"),
):
    for _weight in ("Regular", "Bold"):
        _file = f"{_family}-{_weight}.ttf"
        EXPECTED_FONTS[_file] = (
            _css,
            f"{BASE}/{_family}/hinted/ttf/{_file}",
        )

FAMILIES = sorted({family for family, _ in EXPECTED_FONTS.values()})


def _family_name(path: Path) -> str:
    """Family name via fontTools, else a small name-table parser."""
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(str(path))
        for record in font["name"].names:
            if record.nameID == 1:
                try:
                    text = record.toUnicode()
                except Exception:  # noqa: BLE001, S112 - try next name record
                    continue
                if text:
                    return text
    except ImportError:
        pass
    data = path.read_bytes()
    num_tables = int.from_bytes(data[4:6], "big")
    offset = 12
    name_offset = name_length = 0
    for _ in range(num_tables):
        tag = data[offset : offset + 4]
        table_offset = int.from_bytes(data[offset + 8 : offset + 12], "big")
        table_length = int.from_bytes(data[offset + 12 : offset + 16], "big")
        if tag == b"name":
            name_offset, name_length = table_offset, table_length
            break
        offset += 16
    assert name_offset, "no name table"
    count = int.from_bytes(data[name_offset + 2 : name_offset + 4], "big")
    string_offset = int.from_bytes(data[name_offset + 4 : name_offset + 6], "big")
    fallback = ""
    for index in range(count):
        entry = name_offset + 6 + index * 12
        platform, _encoding, _lang, name_id, length, name_off = (
            int.from_bytes(data[entry + i : entry + i + 2], "big") for i in (0, 2, 4, 6, 8, 10)
        )
        if name_id != 1 or length == 0:
            continue
        start = name_offset + string_offset + name_off
        raw = data[start : start + length]
        try:
            text = raw.decode("utf-16-be" if platform in (0, 3) else "latin1")
        except UnicodeDecodeError:
            continue
        if not fallback:
            fallback = text
        if platform == 3:
            return text
    assert fallback, "no family name"
    assert name_length >= 0
    return fallback


def test_fonts_exist_magic_and_sources():
    assert SOURCES.is_file(), "SOURCES.md missing"
    sources_text = SOURCES.read_text()
    for filename, (family, url) in sorted(EXPECTED_FONTS.items()):
        path = FONTS_DIR / filename
        assert path.is_file(), f"missing {filename}"
        data = path.read_bytes()
        assert data[:4] == b"\x00\x01\x00\x00", f"{filename} bad magic"
        assert 20 * 1024 <= len(data) <= 2 * 1024 * 1024, f"{filename} size {len(data)}"
        assert _family_name(path) == family, f"{filename} family"
        sha256 = hashlib.sha256(data).hexdigest()
        assert filename in sources_text, f"{filename} not in SOURCES.md"
        assert sha256 in sources_text, f"{filename} sha256 not in SOURCES.md"
        assert url in sources_text, f"{filename} url not in SOURCES.md"


def _font_face_blocks(css_text: str) -> list[str]:
    return re.findall(r"@font-face\s*\{[^}]+\}", css_text, re.DOTALL)


def test_app_css_has_font_face_with_unicode_range():
    css_text = CSS.read_text()
    blocks = _font_face_blocks(css_text)
    assert blocks, "no @font-face in app.css"
    for family in FAMILIES:
        matching = [b for b in blocks if family in b]
        assert matching, f"no @font-face for {family}"
        assert any("unicode-range" in b for b in matching), f"no unicode-range for {family}"
        assert any("font-display" in b and "swap" in b for b in matching), (
            f"no font-display: swap for {family}"
        )


def _pdf_font_names(pdf: bytes) -> list[str]:
    import io

    text = pdf.decode("latin1", errors="ignore")
    names = re.findall(r"/(?:FontName|BaseFont)\s*/([^\s/\[\(<>]+)", text)
    names += re.findall(r"/(?:FontName|BaseFont)\s*\(([^)]+)\)", text)
    if names:
        return names
    # WeasyPrint compresses object streams, so fall back to pypdf which
    # decompresses and still reads /BaseFont and /FontName from the bytes.
    from pypdf import PdfReader

    found: list[str] = []
    for page in PdfReader(io.BytesIO(pdf)).pages:
        fonts = ((page.get("/Resources") or {}).get("/Font") or {})
        try:
            items = fonts.items()
        except AttributeError:
            continue
        for _key, ref in items:
            try:
                obj = ref.get_object()
            except Exception:  # noqa: BLE001, S112 - skip unreadable font ref
                continue
            for pdf_key in ("/BaseFont", "/FontName"):
                if pdf_key in obj:
                    found.append(str(obj[pdf_key]))
            for descendant in obj.get("/DescendantFonts", []):
                try:
                    descendant_obj = descendant.get_object()
                except Exception:  # noqa: BLE001, S112 - skip unreadable descendant
                    continue
                for pdf_key in ("/BaseFont", "/FontName"):
                    if pdf_key in descendant_obj:
                        found.append(str(descendant_obj[pdf_key]))
    return names + found


def _bill_pdf(name_local: str, lang: str) -> bytes:
    from app.outputs.bill_pdf import bill_pdf

    shop = {
        "name": f"T44 {name_local}",
        "area": "Koyambedu",
        "phone": "+914400000044",
        "currency": "INR",
    }
    lines = [
        {
            "name_en": "tomato",
            "name_local": name_local,
            "qty": "2",
            "unit": "kg",
            "unit_price": "40",
            "per_amount": "1",
            "line_total": "80",
            "status": "priced",
        }
    ]
    return bill_pdf(shop, 44, lines, "80", "28 Oct 2026", lang=lang)


def test_bill_pdfs_embed_matching_noto():
    cases = {
        "hi": ("टमाटर", "Devanagari"),
        "bn": ("টমেটো", "Bengali"),
        "te": ("టమాటో", "Telugu"),
        "kn": ("ಟೊಮೇಟೊ", "Kannada"),
    }
    for lang, (name_local, needle) in cases.items():
        pdf = _bill_pdf(name_local, lang)
        assert pdf[:5] == b"%PDF-", f"{lang} not a pdf"
        names = _pdf_font_names(pdf)
        assert names, f"{lang} no embedded font names"
        assert any(needle in name for name in names), f"{lang} missing {needle}: {names}"


def test_tamil_bill_pdf_still_embeds_tamil():
    pdf = _bill_pdf("தக்காளி", "ta")
    assert pdf[:5] == b"%PDF-"
    names = _pdf_font_names(pdf)
    assert any("Tamil" in name for name in names), f"Tamil missing: {names}"


def test_modal_app_lists_noto_packages():
    text = MODAL_APP.read_text()
    assert "fonts-noto-core" in text
    assert "fonts-noto-cjk" in text
    assert "fonts-dejavu-core" in text
