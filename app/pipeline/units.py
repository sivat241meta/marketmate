from __future__ import annotations

from decimal import Decimal

from app.models import PriceLine
from app.pipeline.numbers import _words, parse_number

_UNIT_WORDS: dict[str, str] = {
    "kg": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg",
    "kilograms": "kg", "கிலோ": "kg",
    "g": "g", "gram": "g", "grams": "g", "gm": "g", "கிராம்": "g",
    "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
    "dozen": "dozen", "dozens": "dozen", "டஜன்": "dozen",
    "bunch": "bunch", "bunches": "bunch", "kattu": "bunch",
    "kathu": "bunch", "கட்டு": "bunch",
    "packet": "packet", "packets": "packet", "pack": "packet",
    "பாக்கெட்": "packet", "பொட்டலம்": "packet",
}

_G_PER_KG = Decimal(1000)
_PIECES_PER_DOZEN = Decimal(12)
_ML_PER_L = Decimal(1000)

CANONICAL_UNITS = ("kg", "g", "l", "ml", "piece", "dozen", "bunch", "packet")

# Spoken unit words in all 25 registry languages -> canonical unit.
# Only consulted for tokens the model already emitted as a unit, so a word
# that is also a produce name elsewhere is still safe here.
_UNIT_ALIASES: dict[str, str] = {
    # -- kg --
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg",
    "kilogram": "kg", "kilograms": "kg", "kilogramme": "kg",
    "kilogrammes": "kg", "kilogramo": "kg", "kilogramos": "kg",
    "quilo": "kg", "quilos": "kg", "chilo": "kg", "chili": "kg",
    "kiloa": "kg", "kiloan": "kg",
    "킬로": "kg", "킬로그램": "kg", "キロ": "kg", "キログラム": "kg",
    "公斤": "kg", "千克": "kg", "กิโล": "kg", "กิโลกรัม": "kg",
    "ký": "kg", "kí": "kg", "cân": "kg",
    "किलो": "kg", "किलोग्राम": "kg", "কেজি": "kg", "কিলোগ্রাম": "kg",
    "கிலோ": "kg", "கிலோகிராம்": "kg", "కిలో": "kg", "కిలోగ్రాము": "kg",
    "ಕಿಲೋ": "kg", "ಕಿಲೋಗ್ರಾಮ್": "kg", "كيلو": "kg", "كيلوغرام": "kg",
    "קילו": "kg", "קילוגרם": "kg",
    # -- g --
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g",
    "gramme": "g", "grammes": "g", "gramo": "g", "gramos": "g",
    "grama": "g", "gramas": "g", "grammo": "g", "grammi": "g",
    "gramm": "g", "gramy": "g", "gramów": "g", "gam": "g",
    "ग्राम": "g", "গ্রাম": "g", "கிராம்": "g", "గ్రాము": "g",
    "గ్రాములు": "g", "ಗ್ರಾಮ್": "g", "جرام": "g", "גרם": "g",
    "กรัม": "g", "그램": "g", "グラム": "g", "克": "g",
    # -- l --
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "litro": "l", "litros": "l", "litri": "l", "litr": "l", "litry": "l",
    "litra": "l", "lít": "l",
    "लीटर": "l", "लिटर": "l", "লিটার": "l", "லிட்டர்": "l",
    "లీటరు": "l", "ಲೀಟರ್": "l", "لتر": "l", "ליטר": "l", "ลิตร": "l",
    "리터": "l", "リットル": "l", "升": "l", "公升": "l",
    # -- ml --
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "millilitre": "ml", "millilitres": "ml", "mililitro": "ml",
    "mililitros": "ml", "millilitro": "ml", "mililít": "ml",
    "मिलीलीटर": "ml", "মিলিলিটার": "ml", "ملليلتر": "ml",
    "מיליליטר": "ml", "มิลลิลิตร": "ml", "밀리리터": "ml",
    "ミリリットル": "ml", "毫升": "ml",
    # -- piece --
    "piece": "piece", "pieces": "piece", "pc": "piece", "pcs": "piece",
    "unit": "piece", "units": "piece", "each": "piece", "no": "piece",
    "no.": "piece", "nos": "piece", "nos.": "piece",
    "stück": "piece", "stücke": "piece", "pièce": "piece", "pièces": "piece",
    "pezzo": "piece", "pezzi": "piece", "pieza": "piece", "piezas": "piece",
    "unidad": "piece", "unidades": "piece", "unidade": "piece",
    "stuk": "piece", "stuks": "piece", "sztuka": "piece", "sztukę": "piece",
    "sztuki": "piece", "sztuk": "piece", "adet": "piece", "adetler": "piece",
    "tane": "piece", "taneler": "piece", "piraso": "piece",
    "pirasos": "piece", "peraso": "piece", "buah": "piece", "biji": "piece",
    "butir": "piece",
    "개": "piece", "個": "piece", "个": "piece", "只": "piece", "颗": "piece",
    "粒": "piece", "ลูก": "piece", "อัน": "piece", "trái": "piece",
    "quả": "piece", "cái": "piece", "củ": "piece",
    "पीस": "piece", "नग": "piece", "নগ": "piece", "টা": "piece",
    "টি": "piece", "ஒன்று": "piece", "حبة": "piece", "יחידה": "piece",
    # -- dozen --
    "dozen": "dozen", "dozens": "dozen", "doz": "dozen", "doz.": "dozen",
    "douzaine": "dozen", "douzaines": "dozen", "dutzend": "dozen",
    "dozzina": "dozen", "dozzine": "dozen", "docena": "dozen",
    "docenas": "dozen", "dúzia": "dozen", "dúzias": "dozen",
    "dozijn": "dozen", "dozijnen": "dozen", "düzine": "dozen",
    "dosena": "dozen", "tuzin": "dozen", "tuziny": "dozen",
    "lusin": "dozen",
    "다스": "dozen", "打": "dozen", "ダース": "dozen", "โหล": "dozen",
    "tá": "dozen",
    "दर्जन": "dozen", "ডজন": "dozen", "டஜன்": "dozen", "డజను": "dozen",
    "ಡಜನ್": "dozen", "درزن": "dozen", "دستة": "dozen", "תריסר": "dozen",
    # -- bunch --
    "bunch": "bunch", "bunches": "bunch", "kattu": "bunch",
    "kathu": "bunch", "manojo": "bunch", "manojos": "bunch",
    "mazzo": "bunch", "mazzi": "bunch", "botte": "bunch", "bottes": "bunch",
    "bund": "bunch", "bunde": "bunch", "maço": "bunch", "maços": "bunch",
    "bos": "bunch", "bossen": "bunch", "pęczek": "bunch",
    "pęczki": "bunch", "demet": "bunch", "demetler": "bunch",
    "ikat": "bunch", "bó": "bunch", "mớ": "bunch",
    "கட்டு": "bunch", "गुच्छा": "bunch", "गड्डी": "bunch", "আঁটি": "bunch",
    "जुडी": "bunch", "కట్ట": "bunch", "束": "bunch", "把": "bunch",
    "단": "bunch", "송이": "bunch", "กำ": "bunch", "حزمة": "bunch",
    "צרור": "bunch",
    # -- packet --
    "packet": "packet", "packets": "packet", "pack": "packet",
    "pkt": "packet", "sachet": "packet", "sachets": "packet",
    "paquet": "packet", "paquets": "packet", "paquete": "packet",
    "paquetes": "packet", "pacote": "packet", "pacotes": "packet",
    "pacchetto": "packet", "pacchetti": "packet", "packung": "packet",
    "packungen": "packet", "päckchen": "packet", "tüte": "packet",
    "tüten": "packet", "pak": "packet", "pakje": "packet",
    "zakje": "packet", "paczka": "packet", "paczki": "packet",
    "opakowanie": "packet", "paket": "packet", "paketler": "packet",
    "bungkus": "packet", "gói": "packet", "túi": "packet", "bịch": "packet",
    "பாக்கெட்": "packet", "பொட்டலம்": "packet", "पैकेट": "packet",
    "पाकीट": "packet", "প্যাকেট": "packet", "ప్యాకెట్": "packet",
    "ಪ್ಯಾಕೆಟ್": "packet", "كيس": "packet", "שקית": "packet",
    "חבילה": "packet", "ถุง": "packet", "봉지": "packet", "袋": "packet",
    "パック": "packet", "包": "packet",
}

# Units that also rescale the amount: one 斤 is half a kilo, one 两 is 50 g.
_UNIT_SCALES: dict[str, tuple[str, Decimal]] = {
    "斤": ("kg", Decimal("0.5")),
    "两": ("g", Decimal(50)),
    "兩": ("g", Decimal(50)),
}


def normalise_unit(said: str) -> str | None:
    """Map a spoken unit word to kg, g, piece, dozen, bunch or packet."""
    return _UNIT_WORDS.get(said.strip().lower())


_KILO_WORDS = {"kilo", "kilos", "kilogram", "kilograms", "kg", "கிலோ"}


def parse_amount(said: str) -> tuple[Decimal, str] | None:
    """Parse e.g. "kaal kilo", "1 kilo", "oru kattu" into (amount, unit)."""
    words = [w for w in _words(said) if w]
    kilo_said = any(w in _KILO_WORDS for w in words)
    if "kaal" in words or "கால்" in words or ("quarter" in words and kilo_said):
        return (Decimal(250), "g")
    if "arai" in words or "அரை" in words or ("half" in words and kilo_said):
        return (Decimal(500), "g")
    unit: str | None = None
    number_words: list[str] = []
    for w in words:
        found = normalise_unit(w)
        if found is not None and unit is None:
            unit = found
        else:
            number_words.append(w)
    if unit is None:
        return None
    if not number_words:
        return (Decimal(1), unit)
    value = parse_number(" ".join(number_words))
    if value is None:
        return None
    return (value, unit)


def normalize_unit(raw: str | None) -> tuple[str | None, Decimal]:
    """Map a heard unit word to (canonical unit, amount multiplier).

    The canonical set is kg, g, l, ml, piece, dozen, bunch, packet.
    Unknown words return (None, 1); 斤 returns ("kg", 0.5) and 两/兩
    return ("g", 50), so the caller multiplies the amount by the factor.
    """
    if not isinstance(raw, str):
        return (None, Decimal(1))
    key = raw.strip().lower().rstrip(".")
    if not key:
        return (None, Decimal(1))
    scaled = _UNIT_SCALES.get(key)
    if scaled is not None:
        return scaled
    found = _UNIT_ALIASES.get(key)
    if found is None and key.endswith("s") and len(key) > 2:
        found = _UNIT_ALIASES.get(key[:-1])
    if found is None:
        return (None, Decimal(1))
    return (found, Decimal(1))


def normalize_price_line(line: PriceLine) -> None:
    """Canonicalise a price line's unit in place, scaling per_amount.

    Unknown units keep their raw text; check_item raises UNIT_CHECK for
    them, so every path (video, update, approve recheck) flags them once.
    """
    if line.unit is None:
        return
    canonical, factor = normalize_unit(line.unit)
    if canonical is None:
        return
    line.unit = canonical
    if factor != 1 and line.per_amount is not None:
        line.per_amount = line.per_amount * factor


def normalize_qty_unit(unit: str | None, qty: Decimal | None
                       ) -> tuple[str | None, Decimal | None]:
    """Canonicalise a stock quantity unit, scaling the quantity with it."""
    if unit is None:
        return (None, qty)
    canonical, factor = normalize_unit(unit)
    if canonical is None:
        return (unit, qty)
    if factor != 1 and qty is not None:
        qty = qty * factor
    return (canonical, qty)


def convert(amount: Decimal, unit: str, to: str) -> Decimal | None:
    """Convert kg<->g, l<->ml and piece<->dozen. Same unit returns amount."""
    if unit == to:
        return amount
    if unit == "kg" and to == "g":
        return amount * _G_PER_KG
    if unit == "g" and to == "kg":
        return amount / _G_PER_KG
    if unit == "l" and to == "ml":
        return amount * _ML_PER_L
    if unit == "ml" and to == "l":
        return amount / _ML_PER_L
    if unit == "dozen" and to == "piece":
        return amount * _PIECES_PER_DOZEN
    if unit == "piece" and to == "dozen":
        return amount / _PIECES_PER_DOZEN
    return None


def rate(line: PriceLine) -> tuple[Decimal, str] | None:
    """Price per kg (weights), per l (volumes) or per piece (piece/dozen)."""
    if line.price is None or line.per_amount is None or line.unit is None:
        return None
    if line.per_amount == 0:
        return None
    if line.unit in ("kg", "g"):
        amount_kg = convert(line.per_amount, line.unit, "kg")
        if amount_kg is None or amount_kg == 0:
            return None
        return (line.price / amount_kg, "kg")
    if line.unit in ("l", "ml"):
        amount_l = convert(line.per_amount, line.unit, "l")
        if amount_l is None or amount_l == 0:
            return None
        return (line.price / amount_l, "l")
    if line.unit in ("piece", "dozen"):
        amount_piece = convert(line.per_amount, line.unit, "piece")
        if amount_piece is None or amount_piece == 0:
            return None
        return (line.price / amount_piece, "piece")
    if line.unit in ("bunch", "packet"):
        return (line.price / line.per_amount, line.unit)
    return None
