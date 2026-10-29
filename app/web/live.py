"""Live price capture: WebSocket relay browser -> Meta realtime (Task 35).

Task 36 adds live order billing (seller, kind "bill") and live customer
quotes (public, kind "quote") on the same relay pattern. No camera: the
browser streams mic PCM only, and bill/quote lines appear per turn.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from starlette.websockets import WebSocket, WebSocketDisconnect

from app import db
from app.costs import BUDGET_EXHAUSTED_MESSAGE, CostCapExceeded, CostLedger
from app.languages import LANGUAGES, shop_bias
from app.limits import RATE_LIMIT_MESSAGE
from app.market.order_parse import (
    item_like_leftovers,
    leftover_needs_spark,
    parse_order,
)
from app.market.quote import build_quote, wanted_from_text
from app.meta.realtime import RealtimeASR, RealtimeError
from app.meta.spark import SparkError
from app.models import Frame, Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.extract import extract_items, merge_repeated_prices
from app.pipeline.names import display_name_en, display_name_local
from app.pipeline.photos import make_photo  # noqa: F401 - monkeypatch seam
from app.pipeline.run import live_frame_for_item, process_turns
from app.pipeline.scripts import count_letters, dominant_script, expected_scripts
from app.web.i18n import get_ui_lang, t_for

MAX_LIVE_SECONDS = 5 * 60
MAX_QUOTE_LIVE_SECONDS = 60
MAX_FRAME_BYTES = 400 * 1024
MAX_FRAMES_PER_TURN = 2

TIMEOUT_MESSAGE = (
    "We stopped listening after 5 minutes. "
    "Please start again with a shorter recording."
)
QUOTE_TIMEOUT_MESSAGE = (
    "We stopped listening after 60 seconds. "
    "Please start again with a shorter list."
)
LOST_MESSAGE = (
    "We lost the live connection. Please try again, or upload a video instead."
)
_LANG_CODES = {lang.code for lang in LANGUAGES}
START_MESSAGE = (
    "Something went wrong starting live mode. "
    "Please try again, or upload a video instead."
)
NO_ITEMS_MESSAGE = "We could not hear any items. Please try again."
NO_PRICES_MESSAGE = "No price list yet. Record today's prices first."
STOPPED_MESSAGE = "Stopped at 5 minutes – check what we heard"

# Monotonic clock seam: tests patch app.web.live.monotonic with a fake clock.
monotonic = time.monotonic


class IncrementalRunner:
    """Run one extraction at a time; a dirty flag triggers a single rerun."""

    def __init__(self, work) -> None:
        self._work = work
        self._lock = asyncio.Lock()
        self._dirty = False

    async def notify(self) -> None:
        if self._lock.locked():
            self._dirty = True
            return
        async with self._lock:
            while True:
                self._dirty = False
                await self._work()
                if not self._dirty:
                    break


def item_key(item) -> str:
    return f"{item.name_en}|{item.variety or ''}"


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def card_for_item(item, photo_url: str | None) -> dict:
    return {
        "key": item_key(item),
        "name_local": item.name_local,
        "name_en": item.name_en,
        "variety": item.variety,
        "price_lines": [
            {"price": _dec(line.price), "per_amount": _dec(line.per_amount),
             "unit": line.unit, "said": line.said}
            for line in item.price_lines
        ],
        "quote": item.proof.quote,
        "turn_ids": list(item.proof.turn_ids),
        "flags": [
            {"field": flag.field, "code": flag.code, "message": flag.message,
             "options": list(flag.options), "blocking": flag.blocking}
            for flag in item.flags
        ],
        "needs_check": any(flag.blocking or flag.options for flag in item.flags),
        "photo_url": photo_url,
    }


def _ws_ip(websocket: WebSocket) -> str:
    forwarded = websocket.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = websocket.client
    if client is not None:
        host = getattr(client, "host", None)
        if isinstance(host, str) and host:
            return host
        if isinstance(client, (list, tuple)) and client:
            return str(client[0])
    return "unknown"


def _meta_turn_id(data: dict) -> int:
    for key in ("turnId", "turn_id", "turn"):
        if key in data:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                continue
    return 0


def _meta_int(data: dict, keys, default: int) -> int:
    for key in keys:
        if key in data and data[key] is not None:
            try:
                return int(data[key])
            except (TypeError, ValueError):
                continue
    return default


def _display(name: str, variety: str | None = None) -> str:
    return display_name_en(name, variety)


def _order_line_dict(line) -> dict:
    variety = getattr(line, "variety", None)
    return {
        "name_en": line.name_en,
        "variety": variety or "",
        "display": _display(line.name_en or "", variety),
        "name_local": display_name_local(line.name_local or "", variety),
        "qty": str(line.qty),
        "unit": line.unit or "",
        "unit_price": str(line.unit_price) if line.unit_price is not None else None,
        "per_amount": str(line.per_amount) if line.per_amount is not None else None,
        "line_total": str(line.line_total) if line.line_total is not None else None,
        "status": line.status,
        "note": line.note or "",
    }


def _overall_wanted(turns_lines: dict[int, list]) -> list:
    wanted = []
    for turn_id in sorted(turns_lines):
        wanted.extend(turns_lines[turn_id])
    return wanted


def _price_items_for(data_dir: Path, shop_id: int) -> list:
    conn = db.connect(data_dir)
    try:
        version_id = db.latest_version(conn, shop_id, published_only=True)
        if version_id is None:
            return []
        return list(db.version_items(conn, version_id))
    finally:
        conn.close()


def _aliases_for(data_dir: Path, shop_id: int) -> list:
    conn = db.connect(data_dir)
    try:
        return db.shop_name_aliases(conn, shop_id)
    finally:
        conn.close()


def _build_order_payload(data_dir: Path, shop_id: int, wanted: list,
                         event: str) -> dict:
    conn = db.connect(data_dir)
    try:
        quote = build_quote(conn, shop_id, list(wanted))
    finally:
        conn.close()
    return {
        "type": event,
        "lines": [_order_line_dict(line) for line in quote.lines],
        "total": str(quote.total),
    }


async def _run_order_live(websocket: WebSocket, shop: dict,
                          bill_token: str | None, kind: str,
                          settings, data_dir: Path,
                          created_by: str = "owner",
                          contact: dict | None = None) -> None:
    """Relay mic audio to Meta realtime; parse each turn into order lines."""
    is_bill = kind == "bill"
    max_seconds = MAX_LIVE_SECONDS if is_bill else MAX_QUOTE_LIVE_SECONDS
    timeout_msg = TIMEOUT_MESSAGE if is_bill else QUOTE_TIMEOUT_MESSAGE
    lines_event = "bill_lines" if is_bill else "quote_lines"
    language = shop.get("language") or "ta"
    shop_id = shop["id"]
    ledger = CostLedger(data_dir / "costs.db", settings.daily_budget_usd)
    ledger.bind(shop_id=shop_id)
    price_items = _price_items_for(data_dir, shop_id)
    shop_aliases = _aliases_for(data_dir, shop_id)

    await websocket.send_text(json.dumps({"type": "ready"}))
    realtime = RealtimeASR(settings=settings, ledger=ledger,
                           language=language)
    try:
        await realtime.start()
    except CostCapExceeded:
        await websocket.send_text(json.dumps(
            {"type": "error", "message": BUDGET_EXHAUSTED_MESSAGE}))
        await websocket.close()
        return
    except (RealtimeError, Exception):  # noqa: BLE001 - never leak internals
        await websocket.send_text(json.dumps(
            {"type": "error", "message": LOST_MESSAGE}))
        await websocket.close()
        return

    turns_lines: dict[int, list] = {}
    turn_texts: dict[int, str] = {}
    spark_tasks: set[asyncio.Task] = set()
    send_lock = asyncio.Lock()
    stop_requested = asyncio.Event()
    meta_done = asyncio.Event()
    timed_out = False
    start_time = monotonic()
    audio_bytes = 0

    async def send_json(obj: dict) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(obj))

    def _overall():
        return _overall_wanted(turns_lines)

    async def _send_lines() -> None:
        try:
            payload = await asyncio.to_thread(
                _build_order_payload, data_dir, shop_id, _overall(),
                lines_event)
        except Exception:  # noqa: BLE001 - skip one live update
            return
        try:
            await send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            pass

    async def _spark_for_turn(turn_id: int, text: str, local: list) -> None:
        def _run():
            return wanted_from_text(text, ledger=ledger, settings=settings,
                                    step="voice order")

        try:
            wanted = await asyncio.to_thread(_run)
        except (CostCapExceeded, SparkError, Exception):  # noqa: BLE001
            return
        if not wanted:
            return
        local_names = {str(w.name_en or "").strip().lower() for w in local}
        spark_names = {str(w.name_en or "").strip().lower() for w in wanted}
        if not (spark_names - local_names):
            return
        turns_lines[turn_id] = list(wanted)
        await _send_lines()

    async def meta_loop() -> None:
        try:
            async for event in realtime.events():
                if not isinstance(event, dict):
                    continue
                name = str(event.get("type") or event.get("event") or "")
                if name == "speechStart":
                    continue
                if name == "transcript":
                    text = event.get("transcript", event.get("text", ""))
                    if isinstance(text, str) and text.strip():
                        await send_json({"type": "partial", "text": text})
                elif name == "speechEnd":
                    continue
                elif name == "speechComplete":
                    meta_id = _meta_turn_id(event)
                    text = event.get("transcript", event.get("text", "")) or ""
                    turn_id = meta_id + 1
                    await send_json({"type": "turn", "turn_id": turn_id,
                                     "text": str(text)})
                    try:
                        local, leftover = parse_order(
                            str(text), price_items, language,
                            aliases=shop_aliases)
                    except Exception:  # noqa: BLE001 - one bad turn
                        local, leftover = [], [str(text)]
                    turn_texts[turn_id] = str(text)
                    turns_lines[turn_id] = list(local)
                    await _send_lines()
                    if leftover and leftover_needs_spark(leftover):
                        task = asyncio.create_task(
                            _spark_for_turn(turn_id, str(text), list(local)))
                        spark_tasks.add(task)
                        task.add_done_callback(spark_tasks.discard)
                elif name.lower() == "error":
                    raise RealtimeError(str(
                        event.get("message") or "live transcription failed"))
                elif isinstance(event.get("transcript"), str):
                    await send_json({"type": "partial",
                                     "text": event["transcript"]})
        except RealtimeError:
            if not stop_requested.is_set() and not timed_out:
                try:
                    await send_json({"type": "error", "message": LOST_MESSAGE})
                except (WebSocketDisconnect, RuntimeError):
                    pass
            raise
        finally:
            meta_done.set()

    meta_task = asyncio.create_task(meta_loop())
    meta_failed = False
    try:
        while True:
            if monotonic() - start_time > max_seconds:
                timed_out = True
                stop_requested.set()
                try:
                    await send_json({"type": "error", "message": timeout_msg})
                except (WebSocketDisconnect, RuntimeError):
                    pass
                break
            if meta_task.done() and not stop_requested.is_set():
                exc = meta_task.exception()
                if exc is not None:
                    meta_failed = True
                    break
            try:
                message = await asyncio.wait_for(websocket.receive(),
                                                 timeout=1.0)
            except TimeoutError:
                continue
            if message.get("type") == "websocket.disconnect":
                stop_requested.set()
                break
            if message.get("bytes") is not None:
                chunk = bytes(message["bytes"] or b"")
                if not chunk:
                    continue
                audio_bytes += len(chunk)
                try:
                    await realtime.send_audio(chunk)
                except RealtimeError:
                    meta_failed = True
                    try:
                        await send_json({"type": "error",
                                         "message": LOST_MESSAGE})
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    break
                continue
            text = message.get("text")
            if text is None:
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("type") in ("stop", "done"):
                stop_requested.set()
                try:
                    await realtime.end()
                except RealtimeError:
                    pass
                try:
                    await asyncio.wait_for(meta_done.wait(), timeout=12)
                except TimeoutError:
                    pass
                if spark_tasks:
                    _done, pending = await asyncio.wait(
                        set(spark_tasks), timeout=15)
                    for task in pending:
                        task.cancel()
                break
    finally:
        with contextlib.suppress(Exception):
            await realtime.close()
        if not meta_task.done():
            meta_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, RealtimeError,
                                     Exception):
                await meta_task

    if timed_out or meta_failed:
        try:
            await websocket.close()
        except (WebSocketDisconnect, RuntimeError):
            pass
        return
    if not stop_requested.is_set():
        try:
            await websocket.close()
        except (WebSocketDisconnect, RuntimeError):
            pass
        return
    wanted = _overall()
    full_text = " ".join(turn_texts[i] for i in sorted(turn_texts)
                         if turn_texts[i].strip())
    full_leftover: list[str] = []
    if full_text.strip():
        try:
            full_local, full_leftover = parse_order(
                full_text, price_items, language, aliases=shop_aliases)
        except Exception:  # noqa: BLE001 - keep the per-turn lines
            wanted = _overall()
        else:
            merged = list(full_local)
            seen = {str(w.name_en or "").strip().lower() for w in merged}
            for turn_id in sorted(turns_lines):
                for extra in turns_lines[turn_id]:
                    if extra.source == "local":
                        continue
                    key = str(extra.name_en or "").strip().lower()
                    if key and key not in seen:
                        seen.add(key)
                        merged.append(extra)
            wanted = merged
    note_words = item_like_leftovers(
        full_leftover, [w.name_en for w in wanted])
    not_understood = " ".join(note_words) or None
    if not wanted:
        try:
            await send_json({"type": "error", "message": NO_ITEMS_MESSAGE})
        except (WebSocketDisconnect, RuntimeError):
            pass
        try:
            await websocket.close()
        except (WebSocketDisconnect, RuntimeError):
            pass
        return

    def _finalize():
        conn = db.connect(data_dir)
        try:
            version_id = db.latest_version(conn, shop_id, published_only=True)
            if version_id is None:
                return (None, NO_PRICES_MESSAGE)
            quote = build_quote(conn, shop_id, list(wanted))
            if is_bill:
                token = db.create_quote(
                    conn, shop_id=shop_id, quote=quote, source="seller",
                    kind="bill", status="billed", created_by=created_by,
                    not_understood=not_understood)
                row = db.get_quote_by_token(conn, token)
                url = f"/e/{bill_token}/bills/{row['id']}"
                return ({"type": "done", "bill_url": url}, None)
            details = contact or {}
            token = db.create_quote(
                conn, shop_id=shop_id, quote=quote,
                not_understood=not_understood,
                customer_name=details.get("customer_name"),
                customer_phone=details.get("customer_phone"))
            return ({"type": "done", "quote_url": f"/q/{token}"}, None)
        finally:
            conn.close()

    try:
        payload, error = await asyncio.to_thread(_finalize)
    except Exception:  # noqa: BLE001 - final failure becomes an error
        payload, error = None, LOST_MESSAGE
    if error is not None:
        try:
            await send_json({"type": "error", "message": error})
        except (WebSocketDisconnect, RuntimeError):
            pass
    elif payload is not None:
        try:
            await send_json(payload)
        except (WebSocketDisconnect, RuntimeError):
            pass
    try:
        await websocket.close()
    except (WebSocketDisconnect, RuntimeError):
        pass


def register(app: FastAPI, settings, templates: Jinja2Templates) -> None:
    data_dir = Path(settings.data_dir)

    @app.get("/e/{token}/live")
    def live_page(request: Request, token: str):
        from app.web.auth import owner_or_403, resolve_or_404
        from app.web.i18n import get_ui_lang as _ui_lang

        conn = db.connect(data_dir)
        try:
            shop, role, _helper = resolve_or_404(conn, token)
            if shop is None:
                from fastapi import HTTPException

                raise HTTPException(404, "unknown shop token")
            if role != "owner":
                return owner_or_403(request, templates, role,
                                    _ui_lang(request, shop))
            shop_dict = dict(shop)
        finally:
            conn.close()
        from app.web.i18n import get_ui_lang, t_for

        ui_lang = get_ui_lang(request, shop_dict)
        from app.languages import get_language

        shop_lang = shop_dict.get("language") or "ta"
        try:
            shop_native = get_language(shop_lang).native_name
        except KeyError:
            shop_native = "English"
        return templates.TemplateResponse(request, "live.html", {
            "shop": shop_dict, "token": token,
            "notice": t_for(ui_lang)("notice.voice"),
            "shop_lang": shop_lang,
            "shop_native": shop_native,
            "languages": LANGUAGES,
            "max_upload_bytes": app.state.settings.max_upload_bytes,
            "ui_lang": ui_lang,
        })

    @app.get("/e/{token}/s/{session_id}/frame/{name}")
    def live_frame(token: str, session_id: int, name: str):
        from fastapi import HTTPException

        if "/" in name or "\\" in name or not name.endswith(".jpg"):
            raise HTTPException(404, "no such frame")
        if not (name.startswith("turn") and ("_start" in name or "_end" in name)):
            raise HTTPException(404, "no such frame")
        from app.web.auth import resolve_or_404 as _resolve

        conn = db.connect(data_dir)
        try:
            shop, role, _helper = _resolve(conn, token)
            if shop is None:
                raise HTTPException(404, "unknown shop token")
            if role != "owner":
                raise HTTPException(403, "Helpers can only make bills")
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND shop_id = ?",
                (session_id, shop["id"])).fetchone()
            if row is None:
                raise HTTPException(404, "unknown session")
        finally:
            conn.close()
        target = (data_dir / "sessions" / str(session_id) / "frames" / name)
        try:
            resolved = target.resolve()
            base = (data_dir / "sessions" / str(session_id) / "frames").resolve()
        except OSError:
            raise HTTPException(404, "no such frame")
        if base not in resolved.parents and resolved != base:
            raise HTTPException(404, "no such frame")
        if not resolved.is_file():
            raise HTTPException(404, "no such frame")
        return FileResponse(resolved, media_type="image/jpeg")

    @app.websocket("/e/{token}/live/ws")
    async def live_ws(websocket: WebSocket, token: str):
        from app.web.auth import created_by_for, resolve_or_404

        tmp_conn = db.connect(data_dir)
        try:
            db.purge_expired(tmp_conn, data_dir, datetime.now(UTC))
            shop_row, role, helper = resolve_or_404(tmp_conn, token)
            shop = dict(shop_row) if shop_row else None
            made_by = created_by_for(role or "owner", helper)
            is_staff = role == "staff"
        finally:
            tmp_conn.close()
        if shop is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        limiter = app.state.limiter
        if not limiter.allow(_ws_ip(websocket), datetime.now(UTC)):
            await websocket.send_text(json.dumps(
                {"type": "error", "message": RATE_LIMIT_MESSAGE}))
            await websocket.close()
            return
        ledger = CostLedger(data_dir / "costs.db", settings.daily_budget_usd)
        ledger.bind(shop_id=shop["id"])
        try:
            ledger.check()
        except CostCapExceeded:
            await websocket.send_text(json.dumps(
                {"type": "error", "message": BUDGET_EXHAUSTED_MESSAGE}))
            await websocket.close()
            return

        try:
            first = await asyncio.wait_for(websocket.receive(), timeout=15)
        except TimeoutError:
            await websocket.close()
            return
        if first.get("type") == "websocket.disconnect":
            return
        text = first.get("text")
        if text is None:
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        try:
            start_data = json.loads(text)
        except ValueError:
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        if (not isinstance(start_data, dict)
                or start_data.get("type") != "start"
                or start_data.get("kind") not in ("prices", "bill")):
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        if start_data.get("kind") == "bill":
            await _run_order_live(websocket, shop, token, "bill", settings,
                                 data_dir, created_by=made_by)
            return
        if is_staff:
            # Helpers may bill live, but never capture live prices.
            await websocket.send_text(json.dumps(
                {"type": "error",
                 "message": "Helpers can only make bills"}))
            await websocket.close()
            return

        language = shop.get("language") or "ta"
        picked = start_data.get("speak_lang")
        speak_picked = isinstance(picked, str) and picked in _LANG_CODES
        if speak_picked:
            language = picked
        conn = db.connect(data_dir)
        try:
            session_id = db.create_session(conn, shop["id"], "live")
            db.set_session_status(conn, session_id, "processing",
                                  "Listening live...")
            if speak_picked:
                db.set_session_speak_lang(conn, session_id, language)
            previous = db.last_prices(conn, shop["id"])
        finally:
            conn.close()
        ledger.bind(shop_id=shop["id"], session_id=session_id)

        await websocket.send_text(json.dumps(
            {"type": "ready", "session_id": session_id}))

        session_dir = data_dir / "sessions" / str(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        frames_dir = session_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        wav_path = session_dir / "audio.wav"
        try:
            wav_file = wave.open(str(wav_path), "wb")  # noqa: SIM115 - streaming writes
        except OSError:
            conn = db.connect(data_dir)
            try:
                db.set_session_status(conn, session_id, "failed", START_MESSAGE)
            finally:
                conn.close()
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)

        completed: list[Turn] = []
        turn_starts: dict[int, int] = {}
        frames_by_turn: dict[int, dict[str, Frame]] = {}
        frame_counts: dict[int, int] = {}
        audio_bytes = 0
        send_lock = asyncio.Lock()
        stop_requested = asyncio.Event()
        meta_done = asyncio.Event()
        timed_out = False
        start_time = monotonic()

        async def send_json(obj: dict) -> None:
            async with send_lock:
                await websocket.send_text(json.dumps(obj))

        live_ui_lang = get_ui_lang(websocket, shop)
        # Script guard: two captioned turns in a row in an unexpected
        # script offer a language switch. Short captions stay out.
        script_expected = expected_scripts(shop_bias(language))
        script_streak = 0
        script_warned = False

        realtime = RealtimeASR(settings=settings, ledger=ledger,
                               language=language)
        try:
            await realtime.start()
        except CostCapExceeded:
            wav_file.close()
            conn = db.connect(data_dir)
            try:
                db.set_session_status(conn, session_id, "failed",
                                      BUDGET_EXHAUSTED_MESSAGE)
            finally:
                conn.close()
            await send_json({"type": "error",
                             "message": BUDGET_EXHAUSTED_MESSAGE})
            await websocket.close()
            return
        except RealtimeError:
            wav_file.close()
            conn = db.connect(data_dir)
            try:
                db.set_session_status(conn, session_id, "failed", LOST_MESSAGE)
            finally:
                conn.close()
            await send_json({"type": "error", "message": LOST_MESSAGE})
            await websocket.close()
            return
        except Exception:  # noqa: BLE001 - never leak internals
            wav_file.close()
            conn = db.connect(data_dir)
            try:
                db.set_session_status(conn, session_id, "failed", START_MESSAGE)
            finally:
                conn.close()
            await send_json({"type": "error", "message": START_MESSAGE})
            await websocket.close()
            return

        async def do_extract() -> None:
            if not completed:
                return
            snapshot = sorted(completed, key=lambda t: t.id)
            transcript = Transcript(
                text=" ".join(t.text for t in snapshot),
                duration_ms=max(t.end_ms for t in snapshot),
                turns=list(snapshot))

            def _run():
                found = extract_items(transcript, ledger=ledger,
                                      settings=settings, language=language)
                for draft in found:
                    merge_repeated_prices(draft)
                for draft in found:
                    draft.flags.extend(check_item(
                        draft, previous, language=language,
                        ledger=ledger, settings=settings))
                return found

            try:
                found = await asyncio.to_thread(_run)
            except CostCapExceeded:
                await send_json({"type": "error",
                                 "message": BUDGET_EXHAUSTED_MESSAGE})
                return
            except Exception:  # noqa: BLE001 - skip one live update
                return
            cards = []
            for draft in found:
                frame = live_frame_for_item(draft, frames_by_turn, snapshot)
                photo_url = None
                if frame is not None:
                    photo_url = (f"/e/{token}/s/{session_id}/frame/"
                                 f"{Path(str(frame.path)).name}")
                cards.append(card_for_item(draft, photo_url))
            await send_json({"type": "items", "items": cards})

        runner = IncrementalRunner(do_extract)

        async def meta_loop() -> None:
            nonlocal timed_out, script_streak, script_warned
            try:
                async for event in realtime.events():
                    if not isinstance(event, dict):
                        continue
                    kind = str(event.get("type") or event.get("event") or "")
                    if kind == "speechStart":
                        meta_id = _meta_turn_id(event)
                        start_ms = _meta_int(
                            event, ("audioProcessedMs", "startMs", "start_ms"),
                            audio_bytes // 48)
                        turn_starts[meta_id] = start_ms
                        await send_json({"type": "speech_start",
                                         "turn_id": meta_id + 1})
                    elif kind == "transcript":
                        text = event.get("transcript", event.get("text", ""))
                        if isinstance(text, str) and text.strip():
                            await send_json({"type": "partial", "text": text})
                    elif kind == "speechEnd":
                        continue
                    elif kind == "speechComplete":
                        meta_id = _meta_turn_id(event)
                        text = event.get("transcript", event.get("text", "")) or ""
                        start_ms = _meta_int(
                            event, ("startMs", "start_ms"),
                            turn_starts.get(meta_id, audio_bytes // 48))
                        if meta_id in turn_starts and ("startMs" not in event
                                                       and "start_ms" not in event):
                            start_ms = turn_starts[meta_id]
                        end_ms = _meta_int(
                            event, ("endMs", "end_ms", "audioProcessedMs"),
                            audio_bytes // 48)
                        end_ms = max(end_ms, start_ms)
                        turn = Turn(id=meta_id + 1, start_ms=start_ms,
                                    end_ms=end_ms, text=str(text))
                        completed.append(turn)
                        completed.sort(key=lambda t: t.id)
                        await send_json({"type": "turn", "turn_id": turn.id,
                                         "text": turn.text,
                                         "start_ms": turn.start_ms,
                                         "end_ms": turn.end_ms})
                        await runner.notify()
                        if count_letters(turn.text) >= 4:
                            heard = dominant_script(turn.text)
                            if heard not in script_expected:
                                script_streak += 1
                                if script_streak >= 2 and not script_warned:
                                    script_warned = True
                                    warn_t = t_for(live_ui_lang)
                                    if heard == "other":
                                        message = warn_t(
                                            "live.script_warn_other")
                                    else:
                                        message = warn_t(
                                            "live.script_warn", script=heard)
                                    await send_json({"type": "script_warn",
                                                     "script": heard,
                                                     "message": message})
                            else:
                                script_streak = 0
                                script_warned = False
                    elif kind.lower() == "error":
                        raise RealtimeError(str(
                            event.get("message") or "live transcription failed"))
                    else:
                        if isinstance(event.get("transcript"), str):
                            await send_json({"type": "partial",
                                             "text": event["transcript"]})
            except RealtimeError:
                if not stop_requested.is_set() and not timed_out:
                    try:
                        await send_json({"type": "error", "message": LOST_MESSAGE})
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                raise
            finally:
                meta_done.set()

        meta_task = asyncio.create_task(meta_loop())
        meta_failed = False

        try:
            while True:
                if monotonic() - start_time > MAX_LIVE_SECONDS:
                    timed_out = True
                    stop_requested.set()
                    try:
                        await send_json({"type": "timeout",
                                         "message": STOPPED_MESSAGE})
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    try:
                        await realtime.end()
                    except RealtimeError:
                        pass
                    try:
                        await asyncio.wait_for(meta_done.wait(), timeout=12)
                    except TimeoutError:
                        pass
                    break
                if meta_task.done() and not stop_requested.is_set():
                    exc = meta_task.exception()
                    if exc is not None:
                        meta_failed = True
                        conn = db.connect(data_dir)
                        try:
                            db.set_session_status(conn, session_id, "failed",
                                                  LOST_MESSAGE)
                        finally:
                            conn.close()
                        break
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                except TimeoutError:
                    continue
                if message.get("type") == "websocket.disconnect":
                    stop_requested.set()
                    break
                if message.get("bytes") is not None:
                    chunk = bytes(message["bytes"] or b"")
                    if not chunk:
                        continue
                    try:
                        wav_file.writeframes(chunk)
                    except (wave.Error, OSError):
                        pass
                    audio_bytes += len(chunk)
                    try:
                        await realtime.send_audio(chunk)
                    except RealtimeError:
                        meta_failed = True
                        try:
                            await send_json({"type": "error",
                                             "message": LOST_MESSAGE})
                        except (WebSocketDisconnect, RuntimeError):
                            pass
                        conn = db.connect(data_dir)
                        try:
                            db.set_session_status(conn, session_id, "failed",
                                                  LOST_MESSAGE)
                        finally:
                            conn.close()
                        break
                    continue
                text = message.get("text")
                if text is None:
                    continue
                try:
                    data = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                mtype = data.get("type")
                if mtype == "frame":
                    try:
                        turn_no = int(data.get("turn"))
                    except (TypeError, ValueError):
                        continue
                    at = data.get("at")
                    if at not in ("start", "end"):
                        continue
                    jpeg_b64 = data.get("jpeg") or ""
                    if not isinstance(jpeg_b64, str) or not jpeg_b64:
                        continue
                    try:
                        jpeg_bytes = base64.b64decode(jpeg_b64, validate=True)
                    except ValueError:
                        continue
                    if len(jpeg_bytes) > MAX_FRAME_BYTES:
                        continue
                    if len(jpeg_bytes) < 2 or jpeg_bytes[0] != 0xFF:
                        continue
                    fname = f"turn{turn_no}_{at}.jpg"
                    fpath = frames_dir / fname
                    already = fpath.is_file()
                    if not already and frame_counts.get(turn_no, 0) >= MAX_FRAMES_PER_TURN:
                        continue
                    fpath.write_bytes(jpeg_bytes)
                    if not already:
                        frame_counts[turn_no] = frame_counts.get(turn_no, 0) + 1
                    entry = frames_by_turn.setdefault(turn_no, {})
                    entry[at] = Frame(path=fpath, t_ms=audio_bytes // 48)
                    continue
                if mtype == "relang":
                    code = data.get("speak_lang")
                    if not isinstance(code, str) or code not in _LANG_CODES:
                        continue
                    if code == language:
                        await send_json({"type": "relang_ok",
                                         "language": code})
                        continue
                    fresh = RealtimeASR(settings=settings, ledger=ledger,
                                        language=code)
                    try:
                        await fresh.start()
                    except Exception:  # noqa: BLE001 - keep the old session
                        with contextlib.suppress(Exception):
                            await fresh.close()
                        await send_json({"type": "relang_ok",
                                         "language": language})
                        continue
                    stale, realtime = realtime, fresh
                    if not meta_task.done():
                        meta_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError,
                                                 RealtimeError, Exception):
                            await meta_task
                    with contextlib.suppress(Exception):
                        await stale.close()
                    meta_done.clear()
                    meta_task = asyncio.create_task(meta_loop())
                    language = code
                    script_expected = expected_scripts(shop_bias(code))
                    script_streak = 0
                    script_warned = False
                    switch_conn = db.connect(data_dir)
                    try:
                        db.set_session_speak_lang(switch_conn, session_id,
                                                  code)
                    finally:
                        switch_conn.close()
                    await send_json({"type": "relang_ok", "language": code})
                    continue
                if mtype == "stop":
                    stop_requested.set()
                    try:
                        await realtime.end()
                    except RealtimeError:
                        pass
                    try:
                        await asyncio.wait_for(meta_done.wait(), timeout=12)
                    except TimeoutError:
                        pass
                    break
        finally:
            with contextlib.suppress(Exception):
                wav_file.close()
            with contextlib.suppress(Exception):
                await realtime.close()
            if not meta_task.done():
                meta_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, RealtimeError,
                                         Exception):
                    await meta_task

        if meta_failed:
            try:
                await websocket.close()
            except (WebSocketDisconnect, RuntimeError):
                pass
            return
        if not stop_requested.is_set():
            conn = db.connect(data_dir)
            try:
                row = conn.execute("SELECT status FROM sessions WHERE id = ?",
                                   (session_id,)).fetchone()
                if row is not None and row["status"] == "processing":
                    db.set_session_status(conn, session_id, "failed", LOST_MESSAGE)
            finally:
                conn.close()
            try:
                await websocket.close()
            except (WebSocketDisconnect, RuntimeError):
                pass
            return

        def _finalize():
            fin_conn = db.connect(data_dir)
            try:
                turns = sorted(completed, key=lambda t: t.id)
                payload = {
                    "text": " ".join(t.text for t in turns),
                    "duration_ms": max((t.end_ms for t in turns), default=0),
                    "turns": [{"id": t.id, "start_ms": t.start_ms,
                               "end_ms": t.end_ms, "text": t.text}
                              for t in turns],
                }
                (session_dir / "transcript.json").write_text(json.dumps(payload))
                if not turns:
                    db.save_drafts(fin_conn, session_id, [])
                    db.set_stage(fin_conn, session_id, "ready")
                    db.ensure_session_base(fin_conn, session_id)
                    db.set_session_status(fin_conn, session_id, "review",
                                          "No prices heard")
                    return "review"
                process_turns(fin_conn, session_id, turns, frames_by_turn,
                              wav_path, settings=settings, ledger=ledger,
                              language=language)
                return "review"
            finally:
                fin_conn.close()

        try:
            await asyncio.to_thread(_finalize)
            if timed_out:
                conn = db.connect(data_dir)
                try:
                    db.set_session_status(conn, session_id, "review",
                                          STOPPED_MESSAGE)
                finally:
                    conn.close()
        except CostCapExceeded:
            try:
                await send_json({"type": "error",
                                 "message": BUDGET_EXHAUSTED_MESSAGE})
            except (WebSocketDisconnect, RuntimeError):
                pass
            conn = db.connect(data_dir)
            try:
                db.set_session_status(conn, session_id, "failed",
                                      BUDGET_EXHAUSTED_MESSAGE)
            finally:
                conn.close()
            try:
                await websocket.close()
            except (WebSocketDisconnect, RuntimeError):
                pass
            return
        except Exception:  # noqa: BLE001 - final failure becomes a status
            conn = db.connect(data_dir)
            try:
                db.set_session_status(conn, session_id, "failed", LOST_MESSAGE)
            finally:
                conn.close()
            try:
                await send_json({"type": "error", "message": LOST_MESSAGE})
            except (WebSocketDisconnect, RuntimeError):
                pass
            try:
                await websocket.close()
            except (WebSocketDisconnect, RuntimeError):
                pass
            return

        done_payload: dict = {
            "type": "done", "review_url": f"/e/{token}/s/{session_id}"}
        if timed_out:
            done_payload["message"] = STOPPED_MESSAGE
        try:
            await send_json(done_payload)
        except (WebSocketDisconnect, RuntimeError):
            pass
        try:
            await websocket.close()
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.websocket("/s/{slug}/quote/ws")
    async def quote_ws(websocket: WebSocket, slug: str):
        tmp_conn = db.connect(data_dir)
        try:
            db.purge_expired(tmp_conn, data_dir, datetime.now(UTC))
            shop_row = db.shop_by_slug(tmp_conn, slug)
            shop = dict(shop_row) if shop_row else None
        finally:
            tmp_conn.close()
        if shop is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        limiter = app.state.limiter
        if not limiter.allow(_ws_ip(websocket), datetime.now(UTC)):
            await websocket.send_text(json.dumps(
                {"type": "error", "message": RATE_LIMIT_MESSAGE}))
            await websocket.close()
            return
        ledger = CostLedger(data_dir / "costs.db", settings.daily_budget_usd)
        try:
            ledger.check()
        except CostCapExceeded:
            await websocket.send_text(json.dumps(
                {"type": "error", "message": BUDGET_EXHAUSTED_MESSAGE}))
            await websocket.close()
            return
        try:
            first = await asyncio.wait_for(websocket.receive(), timeout=15)
        except TimeoutError:
            await websocket.close()
            return
        if first.get("type") == "websocket.disconnect":
            return
        text = first.get("text")
        if text is None:
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        try:
            start_data = json.loads(text)
        except ValueError:
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        if (not isinstance(start_data, dict)
                or start_data.get("type") != "start"
                or start_data.get("kind") != "quote"):
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        from app.web.i18n import t_for as _t_for
        from app.web.quotes import (
            clean_customer_name,
            clean_customer_phone,
            customer_name_ok,
            customer_phone_ok,
        )

        ws_lang = start_data.get("lang") or "en"
        if ws_lang not in ("en", "ta", "hi"):
            ws_lang = "en"
        ws_t = _t_for(ws_lang)
        contact = {"customer_name": None, "customer_phone": None}
        raw_name = start_data.get("customer_name")
        raw_phone = start_data.get("customer_phone")
        if raw_name is not None or raw_phone is not None:
            name = clean_customer_name(raw_name)
            phone = clean_customer_phone(raw_phone)
            if raw_name is not None and not customer_name_ok(name):
                await websocket.send_text(json.dumps(
                    {"type": "error",
                     "message": ws_t("order.name_required")}))
                await websocket.close()
                return
            if raw_phone is not None and not customer_phone_ok(phone):
                await websocket.send_text(json.dumps(
                    {"type": "error",
                     "message": ws_t("order.phone_invalid")}))
                await websocket.close()
                return
            contact = {"customer_name": name or None,
                       "customer_phone": phone or None}
        await _run_order_live(websocket, shop, None, "quote", settings,
                             data_dir, contact=contact)
