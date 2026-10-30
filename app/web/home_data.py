"""Marketplace homepage data (Task 84): live shops, picks, markets."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app import db
from app.config import sample_shops_enabled
from app.market.hours import IST, shop_open_status
from app.pipeline.photos import is_cutout_photo
from app.web.i18n import SAMPLE_TIME, first_grapheme, tile_variety

MAX_PICKS = 8
MAX_POPULAR = 6
MAX_SHOPS = 4
NEW_SHOP_DAYS = 7


def _as_aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _photo_url(photo: str | None) -> str | None:
    if not photo:
        return None
    return "/m/" + Path(photo).name


def _per_text(per_amount, unit) -> str:
    if per_amount is not None and unit:
        return f"{per_amount} {unit}"
    if unit:
        return str(unit)
    if per_amount is not None:
        return str(per_amount)
    return ""


def _script_lang(text: str | None) -> str:
    """UI language matching the text's own script: ta/hi for Indic, else en.

    Same Indic ranges as ``app.pipeline.names._has_indic`` (0x0900-0x0DFF),
    split into Devanagari (hi) and Tamil (ta) so the card can set a ``lang``
    attribute and CSS ``:lang()`` rules wrap Tamil/Hindi instead of
    clipping them with an ellipsis.
    """
    for char in text or "":
        code = ord(char)
        if 0x0B80 <= code <= 0x0BFF:
            return "ta"
        if 0x0900 <= code <= 0x097F:
            return "hi"
    return "en"


def _parse_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def live_shops(conn: sqlite3.Connection, now: datetime,
               *, settings=None) -> list[dict]:
    """Listed shops whose published list was said today (IST).

    Unlisted shops, shops without a published version, and shops whose
    list is older than today never appear. Sample shops are the
    exception: they show whenever enabled (SAMPLE_SHOPS=0 hides them),
    however old their list is — they never count as "said today".
    Each entry carries the shop row, the said moment, and its live
    items (priced, not sold out).
    """
    today = _as_aware(now).astimezone(IST).date()
    show_samples = sample_shops_enabled(settings)
    rows = conn.execute(
        "SELECT * FROM shops WHERE listed = 1 ORDER BY id").fetchall()
    out = []
    for shop in rows:
        is_sample = bool(shop["is_demo"])
        if is_sample and not show_samples:
            continue
        version_id = db.latest_version(conn, shop["id"], published_only=True)
        if version_id is None:
            continue
        said = _as_aware(db.version_time(conn, version_id))
        if not is_sample and said.astimezone(IST).date() != today:
            continue
        items = [item for item in db.version_items(conn, version_id)
                 if not item.sold_out
                 and any(line.price is not None
                         for line in item.price_lines)]
        out.append({"shop": shop, "said": said, "items": items})
    return out


def _first_price(item):
    for line in item.price_lines:
        if line.price is not None:
            return line
    return None


def _pick_cards(entries: list[dict]) -> list[dict]:
    cards = []
    for entry in entries:
        shop = entry["shop"]
        is_sample = bool(shop["is_demo"])
        # Sample shops render "Sample prices", never "said today HH:MM".
        said = (SAMPLE_TIME if is_sample
                else entry["said"].astimezone(IST).strftime("%H:%M"))
        status = shop_open_status(shop)
        cover_url = _photo_url(db.shop_cover(shop))
        for item in entry["items"]:
            line = _first_price(item)
            if line is None:
                continue
            cutout = is_cutout_photo(item.photo)
            cards.append({
                "photo_url": _photo_url(item.photo),
                "photo_cutout": cutout,
                "photo_rank": (0 if cutout else
                               1 if item.photo else 2),
                "tile": first_grapheme(item.name_local or item.name_en),
                "tile_var": tile_variety(item.variety),
                "variety": item.variety or "",
                "price": str(line.price),
                "per": _per_text(line.per_amount, line.unit),
                "name_local": item.name_local,
                "name_en": item.name_en,
                "shop_name": shop["name"],
                "shop_name_lang": _script_lang(shop["name"]),
                "slug": shop["slug"],
                "area": shop["area"] or "",
                "area_lang": _script_lang(shop["area"]),
                "said": said,
                "open_state": status["state"],
                "open_time": status["time"],
                "is_demo": is_sample,
                "cover_url": cover_url,
                "currency": shop["currency"] or "INR",
                "shop_lang": shop["language"] or "en",
            })
    cards.sort(key=lambda card: (card["is_demo"], card["photo_rank"]))
    return cards[:MAX_PICKS]


def _popular(entries: list[dict]) -> list[dict]:
    """Most common live item names by number of shops, max 6.

    Each entry carries a photo when any live item with that name has
    one (a cut-out wins over a plain crop), so the search pop-up
    shows the photo instead of a letter circle.
    """
    shops_per_name: dict[str, set[str]] = {}
    display: dict[str, str] = {}
    photos: dict[str, tuple[str, bool]] = {}
    for entry in entries:
        slug = entry["shop"]["slug"]
        for item in entry["items"]:
            key = (item.name_en or "").strip().lower()
            if not key:
                continue
            shops_per_name.setdefault(key, set()).add(slug)
            display.setdefault(key, item.name_en.strip())
            if item.photo:
                cutout = is_cutout_photo(item.photo)
                prev = photos.get(key)
                if prev is None or (cutout and not prev[1]):
                    photos[key] = (_photo_url(item.photo), cutout)
    ranked = sorted(shops_per_name,
                    key=lambda key: (-len(shops_per_name[key]), key))
    out = []
    for key in ranked[:MAX_POPULAR]:
        url, cutout = photos.get(key, (None, False))
        out.append({"name": display[key],
                    "shops": len(shops_per_name[key]),
                    "photo_url": url,
                    "photo_cutout": cutout})
    return out


def _shop_card(entry: dict, now: datetime) -> dict:
    shop = entry["shop"]
    items = entry["items"]
    priced = [(item, _first_price(item)) for item in items]
    priced = [(item, line) for item, line in priced if line is not None]
    photo = photo_cutout = None
    for item in sorted(items,
                       key=lambda it: (0 if is_cutout_photo(it.photo)
                                       else 1 if it.photo else 2)):
        if item.photo:
            photo, photo_cutout = _photo_url(item.photo), \
                is_cutout_photo(item.photo)
            break
    cheapest = sorted(priced, key=lambda pair: pair[1].price)[:3]
    status = shop_open_status(shop)
    moment = _parse_moment(shop["created_at"])
    return {
        "name": shop["name"],
        "slug": shop["slug"],
        "area": shop["area"] or "",
        "is_demo": bool(shop["is_demo"]),
        "is_new": bool(moment is not None
                       and (_as_aware(now) - moment).days < NEW_SHOP_DAYS),
        "open_state": status["state"],
        "open_time": status["time"],
        "n_prices": sum(len(item.price_lines) for item in items),
        "photo_url": photo,
        "photo_cutout": bool(photo_cutout),
        "cover_url": _photo_url(db.shop_cover(shop)),
        "tile": first_grapheme(shop["name"]),
        "cheapest": [{"name": item.name_en,
                      "price": str(line.price),
                      "currency": shop["currency"] or "INR"}
                     for item, line in cheapest],
    }


def _shop_cards(entries: list[dict], now: datetime) -> list[dict]:
    def created(entry):
        return _parse_moment(entry["shop"]["created_at"]) or _as_aware(now)

    # Newest first, but sample shops always after real shops (the
    # second sort is stable, so each group stays newest-first).
    ordered = sorted(entries, key=created, reverse=True)
    ordered.sort(key=lambda entry: bool(entry["shop"]["is_demo"]))
    return [_shop_card(entry, now) for entry in ordered[:MAX_SHOPS]]


def _haversine_km(a_lat, a_lng, b_lat, b_lng) -> float:
    radius = 6371.0
    lat1, lat2 = math.radians(a_lat), math.radians(b_lat)
    gap = math.asin(math.sqrt(
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(math.radians(b_lng - a_lng) / 2) ** 2))
    return 2 * radius * gap


def _nearby_fillers(entries: list[dict], picked: str, have: int,
                    coords: dict[str, tuple], now: datetime) -> list[dict]:
    """Cards from other areas to fill the top-shops row up to 4.

    Only for a known picked area with fewer than 4 shops of its own:
    closest first when the picked area's location is known (a shop
    without coordinates sorts after every shop with them), sample
    shops always last. Unknown areas stay empty so the page stays
    honest; callers hide the carousel when nothing fills it.
    """
    need = MAX_SHOPS - have
    if need <= 0:
        return []
    others = [entry for entry in entries
              if (entry["shop"]["area"] or "") != picked]
    center = coords.get(picked)

    def position(entry):
        shop = entry["shop"]
        if shop["lat"] is not None and shop["lng"] is not None:
            return (shop["lat"], shop["lng"])
        return coords.get(shop["area"] or "", (None, None))

    def distance(entry):
        if center is None or center[0] is None:
            return None
        lat, lng = position(entry)
        if lat is None or lng is None:
            return None
        return _haversine_km(center[0], center[1], lat, lng)

    def created(entry):
        moment = _parse_moment(entry["shop"]["created_at"])
        return moment or _as_aware(now)

    scored = [(bool(entry["shop"]["is_demo"]),
               distance(entry) is None,
               distance(entry) or 0.0,
               entry)
              for entry in others]
    # Newest first within equal distance (stable: sort by created
    # first, then by the keys above).
    scored.sort(key=lambda row: created(row[3]), reverse=True)
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return [_shop_card(row[3], now) for row in scored[:need]]


def _area_tiles(entries: list[dict]) -> list[dict]:
    by_area: dict[str, list[dict]] = {}
    for entry in entries:
        by_area.setdefault(entry["shop"]["area"] or "", []).append(entry)
    tiles = []
    for name in sorted(by_area):
        group = by_area[name]
        photo = photo_cutout = lat = lng = None
        from_cover = False
        for entry in group:
            shop = entry["shop"]
            if lat is None and shop["lat"] is not None \
                    and shop["lng"] is not None:
                lat, lng = shop["lat"], shop["lng"]
            # The area photo is the first shop cover in the area; item
            # photos are only the fallback when no shop has a cover.
            if not from_cover:
                cover = _photo_url(db.shop_cover(shop))
                if cover is not None:
                    photo, photo_cutout = cover, False
                    from_cover = True
                    continue
            if from_cover:
                continue
            for item in entry["items"]:
                if not item.photo:
                    continue
                if photo is None or is_cutout_photo(item.photo):
                    photo = _photo_url(item.photo)
                    photo_cutout = is_cutout_photo(item.photo)
                if photo_cutout:
                    break
        tiles.append({
            "name": name,
            "n_shops": len(group),
            "m_prices": sum(len(item.price_lines)
                            for entry in group for item in entry["items"]),
            "photo_url": photo,
            "photo_cutout": bool(photo_cutout),
            "lat": lat,
            "lng": lng,
        })
    return tiles


def home_data(conn: sqlite3.Connection, area: str | None = None,
              now: datetime | None = None, *, settings=None) -> dict:
    """Everything the marketplace homepage renders, filtered by area name."""
    moment = _as_aware(now) if now is not None else datetime.now(UTC)
    entries = live_shops(conn, moment, settings=settings)
    known = sorted({(entry["shop"]["area"] or "")
                    for entry in entries if entry["shop"]["area"]})
    picked: str | None = None
    if (area or "").strip():
        needle = area.strip().lower()
        for name in known:
            if name.lower() == needle:
                picked = name
                break
        else:
            # Unknown area: match nothing, so every section stays honest.
            picked = area.strip()
    scoped = [entry for entry in entries
              if picked is None or (entry["shop"]["area"] or "") == picked]
    coords: dict[str, tuple] = {}
    for entry in entries:
        shop = entry["shop"]
        name = shop["area"] or ""
        if name not in coords and shop["lat"] is not None \
                and shop["lng"] is not None:
            coords[name] = (shop["lat"], shop["lng"])
    show_samples = sample_shops_enabled(settings)
    covers: dict[str, str] = {}
    cover_rows = conn.execute(
        "SELECT area, cover_photo FROM shops WHERE listed = 1"
        + ("" if show_samples else " AND is_demo = 0")
        + " ORDER BY id").fetchall()
    for row in cover_rows:
        name = row["area"] or ""
        if name and name not in covers and row["cover_photo"]:
            covers[name] = _photo_url(row["cover_photo"])
    areas = [{"name": name, "lat": coords.get(name, (None, None))[0],
              "lng": coords.get(name, (None, None))[1],
              "photo_url": covers.get(name)}
             for name in db.listed_areas(
                 conn, include_samples=show_samples)]
    real = [entry for entry in entries
            if not entry["shop"]["is_demo"]]
    samples = [entry for entry in entries
               if entry["shop"]["is_demo"]]
    shops = _shop_cards(scoped, moment)
    # Task 125: the top-shops carousel never shows a near-empty row —
    # a known area with fewer than 4 shops borrows the closest shops
    # from other areas ("and nearby markets"). Unknown areas and the
    # unfiltered page keep exactly their own shops.
    fillers = (_nearby_fillers(entries, picked, len(shops), coords,
                               moment)
               if picked is not None and picked in known
               else [])
    return {
        "area": picked,
        "areas": areas,
        "tiles": _area_tiles(entries),
        "top_shops": shops + fillers,
        "top_nearby": bool(fillers),
        "totals": {
            # Counters never imply sample prices were said today:
            # n_shops/m_prices cover real shops only; sample shops
            # get their own counts and a separate "+ N sample shops"
            # note (or a "Prices listed" label when nothing is real).
            "n_shops": len(real),
            "m_prices": sum(len(item.price_lines)
                            for entry in real
                            for item in entry["items"]),
            "n_sample_shops": len(samples),
            "m_sample_prices": sum(len(item.price_lines)
                                   for entry in samples
                                   for item in entry["items"]),
        },
        "picks": _pick_cards(scoped),
        "popular": _popular(scoped),
        "shops": shops,
    }
