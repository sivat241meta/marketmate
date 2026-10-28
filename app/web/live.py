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
from app.limits import RATE_LIMIT_MESSAGE
from app.market.order_parse import leftover_needs_spark, parse_order
from app.market.quote import build_quote, wanted_from_text
from app.meta.realtime import RealtimeASR, RealtimeError
from app.meta.spark import SparkError
from app.models import Frame, Transcript, Turn
from app.pipeline.checks import check_item
from app.pipeline.extract import extract_items
from app.pipeline.photos import make_photo  # noqa: F401 - monkeypatch seam
from app.pipeline.run import live_frame_for_item, process_turns

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
START_MESSAGE = (
    "Something went wrong starting live mode. "
    "Please try again, or upload a video instead."
)
NO_ITEMS_MESSAGE = "We could not hear any items. Please try again."
NO_PRICES_MESSAGE = "No price list yet. Record today's prices first."


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


def _display(name: str) -> str:
    return name[:1].upper() + name[1:] if name else name


def _order_line_dict(line) -> dict:
    return {
        "name_en": line.name_en,
        "display": _display(line.name_en or ""),
        "name_local": line.name_local or "",
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
                          settings, data_dir: Path) -> None:
    """Relay mic audio to Meta realtime; parse each turn into order lines."""
    is_bill = kind == "bill"
    max_seconds = MAX_LIVE_SECONDS if is_bill else MAX_QUOTE_LIVE_SECONDS
    timeout_msg = TIMEOUT_MESSAGE if is_bill else QUOTE_TIMEOUT_MESSAGE
    lines_event = "bill_lines" if is_bill else "quote_lines"
    language = shop.get("language") or "ta"
    shop_id = shop["id"]
    ledger = CostLedger(data_dir / "costs.db", settings.daily_budget_usd)
    price_items = _price_items_for(data_dir, shop_id)

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
    send_lock = asyncio.Lock()
    stop_requested = asyncio.Event()
    meta_done = asyncio.Event()
    timed_out = False
    start_time = time.monotonic()
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
            return wanted_from_text(text, ledger=ledger, settings=settings)

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
                            str(text), price_items, language)
                    except Exception:  # noqa: BLE001 - one bad turn
                        local, leftover = [], [str(text)]
                    turns_lines[turn_id] = list(local)
                    await _send_lines()
                    if leftover and leftover_needs_spark(leftover):
                        asyncio.create_task(
                            _spark_for_turn(turn_id, str(text), list(local)))
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
            if time.monotonic() - start_time > max_seconds:
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
                    kind="bill", status="billed")
                row = db.get_quote_by_token(conn, token)
                url = f"/e/{bill_token}/bills/{row['id']}"
                return ({"type": "done", "bill_url": url}, None)
            token = db.create_quote(conn, shop_id=shop_id, quote=quote)
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
        conn = db.connect(data_dir)
        try:
            shop = db.shop_by_token(conn, token)
            if shop is None:
                from fastapi import HTTPException

                raise HTTPException(404, "unknown shop token")
            shop_dict = dict(shop)
        finally:
            conn.close()
        from app.web.seller import NOTICE

        return templates.TemplateResponse(request, "live.html", {
            "shop": shop_dict, "token": token, "notice": NOTICE,
            "shop_lang": shop_dict.get("language") or "ta",
            "max_upload_bytes": app.state.settings.max_upload_bytes,
        })

    @app.get("/e/{token}/s/{session_id}/frame/{name}")
    def live_frame(token: str, session_id: int, name: str):
        from fastapi import HTTPException

        if "/" in name or "\\" in name or not name.endswith(".jpg"):
            raise HTTPException(404, "no such frame")
        if not (name.startswith("turn") and ("_start" in name or "_end" in name)):
            raise HTTPException(404, "no such frame")
        conn = db.connect(data_dir)
        try:
            shop = db.shop_by_token(conn, token)
            if shop is None:
                raise HTTPException(404, "unknown shop token")
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
        tmp_conn = db.connect(data_dir)
        try:
            db.purge_expired(tmp_conn, data_dir, datetime.now(UTC))
            shop_row = db.shop_by_token(tmp_conn, token)
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
                or start_data.get("kind") not in ("prices", "bill")):
            await websocket.send_text(json.dumps(
                {"type": "error", "message": START_MESSAGE}))
            await websocket.close()
            return
        if start_data.get("kind") == "bill":
            await _run_order_live(websocket, shop, token, "bill", settings,
                                 data_dir)
            return

        language = shop.get("language") or "ta"
        conn = db.connect(data_dir)
        try:
            session_id = db.create_session(conn, shop["id"], "live")
            db.set_session_status(conn, session_id, "processing",
                                  "Listening live...")
            previous = db.last_prices(conn, shop["id"])
        finally:
            conn.close()

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
        start_time = time.monotonic()

        async def send_json(obj: dict) -> None:
            async with send_lock:
                await websocket.send_text(json.dumps(obj))

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
            nonlocal timed_out
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
                if time.monotonic() - start_time > MAX_LIVE_SECONDS:
                    timed_out = True
                    stop_requested.set()
                    try:
                        await send_json({"type": "error", "message": TIMEOUT_MESSAGE})
                    except (WebSocketDisconnect, RuntimeError):
                        pass
                    conn = db.connect(data_dir)
                    try:
                        db.set_session_status(conn, session_id, "failed",
                                              TIMEOUT_MESSAGE)
                    finally:
                        conn.close()
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

        if timed_out or meta_failed:
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

        try:
            await send_json({"type": "done",
                             "review_url": f"/e/{token}/s/{session_id}"})
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
        await _run_order_live(websocket, shop, None, "quote", settings,
                             data_dir)
