"""Benchmark the pipeline on the synthetic language clips.

Usage: .venv/bin/python scripts/lang_benchmark.py [--only ta,hi,...]
       [--provider meta|baseten] [--from-json]

For each language in eval/lang/scripts.json with a macOS test voice and a
built clip (see scripts/make_lang_clips.py), creates a temporary shop with
that language code, runs the normal pipeline
(app.pipeline.run.process_video_session) on eval/clips/lang/{code}.mp4,
scores with scripts.benchmark.compare_clips, and records Meta cost from
the ledger plus seconds.

Writes eval/out/lang_results.json and regenerates docs/languages.md.
Stops early if the daily cost cap is hit, keeping partial results.
The owner's reviewer runs this live (it calls the network).

With --from-json, docs/languages.md is rebuilt from the saved
eval/out/lang_results.json without calling the network.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.benchmark import (
    _match_item,
    compare_clips,
    normalize_variety,
    score_item,
)
from scripts.make_lang_clips import load_scripts, select_voice

ROOT = Path(__file__).resolve().parent.parent
CLIPS_DIR = ROOT / "eval" / "clips" / "lang"
OUT_JSON = ROOT / "eval" / "out" / "lang_results.json"
DOC_PATH = ROOT / "docs" / "languages.md"


def score_lang(key: dict, out: dict) -> dict:
    """Score one language with the existing benchmark scoring code."""
    row = compare_clips(key, out)
    return {
        "in_key": row["in_key"],
        "found": row["found"],
        "exact": row["exact"],
        "flagged": row["flagged"],
        "wrong_unflagged": row["unflagged"],
        "missed": row["in_key"] - row["found"],
    }


def detail_items(key: dict, out: dict) -> list[dict]:
    """Per-item detail: want, got lines, flags with options, quote, verdict."""
    out_items = out.get("items", [])
    detail: list[dict] = []
    for key_item in key.get("items", []):
        out_item = _match_item(
            out_items, str(key_item.get("name_en", "")).lower(),
            normalize_variety(key_item.get("variety")))
        entry = {
            "name_en": key_item.get("name_en", ""),
            "want": {"price": key_item.get("price"),
                     "per_amount": key_item.get("per_amount"),
                     "unit": key_item.get("unit")},
            "got": [],
            "flags": [],
            "quote": "",
            "verdict": score_item(key_item, out_item),
        }
        if out_item is not None:
            entry["got"] = [
                {"price": line.get("price"),
                 "per_amount": line.get("per_amount"),
                 "unit": line.get("unit")}
                for line in out_item.get("price_lines", [])]
            entry["flags"] = [
                {"code": flag.get("code"), "message": flag.get("message", ""),
                 "options": list(flag.get("options", [])),
                 "blocking": bool(flag.get("blocking", True))}
                for flag in out_item.get("flags", [])]
            proof = out_item.get("proof") or {}
            entry["quote"] = proof.get("quote", "") or ""
        detail.append(entry)
    return detail


def notes_for(result: dict) -> str:
    """Table notes; never claims an untested or wrong language works."""
    if result.get("status") == "not_tested":
        reason = result.get("reason", "no test voice") or "no test voice"
        if reason == "no test voice":
            return "not tested (no test voice)"
        return f"not tested ({reason})"
    in_key = result.get("in_key", 4)
    if result.get("wrong_unflagged", 0) > 0 or result.get("missed", 0) > 0:
        return "needs work"
    if result.get("found", in_key) < in_key:
        return "needs work"
    if result.get("exact", 0) < in_key:
        return "flagged only"
    return "ok"


def _same_number(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except InvalidOperation:
        return str(left) == str(right)


def miss_line(api_name: str, entry: dict, transcript: str = "") -> str:
    """One 'What went wrong' line for a non-exact benchmark item."""
    name = entry.get("name_en", "")
    head = f"{api_name} - {name}"
    if entry.get("verdict") == "missed":
        if name and name.lower() in (transcript or "").lower():
            return f"{head}: heard but not extracted"
        return f"{head}: not in the transcript (speech step lost the sentence)"
    want = entry.get("want") or {}
    got_lines = entry.get("got") or []
    first = next((got for got in got_lines if got.get("price") is not None),
                 None)
    if first is None:
        desc = f"no price heard (wanted {want.get('price')})"
    else:
        price, unit = first.get("price"), first.get("unit")
        price_wrong = not _same_number(price, want.get("price"))
        unit_wrong = (unit or None) != (want.get("unit") or None)
        if price_wrong and unit_wrong:
            desc = (f"heard {price} per {unit} instead of "
                    f"{want.get('price')} per {want.get('unit')}")
        elif price_wrong:
            desc = f"heard {price} instead of {want.get('price')}"
        elif unit_wrong:
            desc = f"unit {unit} instead of {want.get('unit')}"
        else:
            desc = f"heard {price}"
    blocking = [flag for flag in entry.get("flags", [])
                if flag.get("blocking", True)]
    if blocking:
        desc += f" (flagged: {blocking[0].get('message', '')})"
    else:
        desc += " (no warning shown)"
    return f"{head}: {desc}"


def what_went_wrong_lines(results: list[dict]) -> list[str]:
    """One line per non-exact item, in table order."""
    lines = []
    for res in results:
        if res.get("status") == "not_tested":
            continue
        for entry in res.get("items", []) or []:
            if entry.get("verdict") not in ("exact", None):
                lines.append(miss_line(res.get("api_name", ""),
                                       entry, res.get("transcript", "")))
    return lines


def render_languages_md(results: list[dict], provider: str = "meta") -> str:
    """Full docs/languages.md: intro, one row per language, summary line."""
    lines = [
        "# Languages",
        "",
        "MarketMate accepts all 25 Muse Voice languages. The shop form lists",
        "every language by native name, and Voice Transcribe is called with",
        "`languageBias` set to the shop language plus English.",
        "",
        "## Synthetic benchmark",
        "",
        "These results come from synthetic test clips, not real market",
        "recordings: each clip pairs a macOS voice speaking 4 items with",
        "Wikimedia photos of those items. Every language uses the same",
        "4 items (tomato, onion, banana, coconut) with local-currency test",
        "prices; see `eval/lang/scripts.json`.",
        "There was one run per language, and results vary run to run.",
        '"wrong-unflagged" means a wrong price or unit shown with no warning;',
        '"flagged only" means every miss was flagged (honest, but the seller',
        "must tap to fix it).",
        "",
        f"Provider for text steps: `{provider}` (image steps always use Meta).",
        "",
        (
            "| native name | English name | voice | found/4 | exact/4 | "
            "flagged | wrong-unflagged | cost | seconds | notes |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for res in results:
        voice = res.get("voice") or "-"
        lines.append(
            f"| {res.get('native_name', '')} | {res.get('api_name', '')} | "
            f"{voice} | {res.get('found', 0)}/4 | {res.get('exact', 0)}/4 | "
            f"{res.get('flagged', 0)} | {res.get('wrong_unflagged', 0)} | "
            f"${float(res.get('cost_usd', 0.0)):.4f} | "
            f"{float(res.get('seconds', 0.0)):.1f} | {notes_for(res)} |"
        )
    tested = [r for r in results if r.get("status") != "not_tested"]
    perfect = [
        r for r in tested
        if r.get("exact", 0) == 4 and r.get("wrong_unflagged", 0) == 0
    ]
    flagged_only = [r for r in tested if notes_for(r) == "flagged only"]
    needy = [r for r in tested if notes_for(r) == "needs work"]
    untested = [r for r in results if r.get("status") == "not_tested"]
    lines += [
        "",
        (
            f"Summary: tested {len(tested)} of {len(results)} languages; "
            f"{len(perfect)} reached 4/4 exact with no wrong-unflagged; "
            f"{len(flagged_only)} flagged only; "
            f"{len(needy)} need work; "
            f"{len(untested)} not tested (no test voice or no clip)."
        ),
        "",
        "## What went wrong",
        "",
    ]
    misses = what_went_wrong_lines(results)
    if misses:
        lines.extend(f"- {line}" for line in misses)
    elif any(res.get("items") for res in tested):
        lines.append("No misses: every tested item was exact.")
    else:
        lines.append("Per-item detail was not recorded in this run"
                     " (re-run the benchmark to see it).")
    lines.append("")
    return "\n".join(lines)


def _say_output() -> str:
    try:
        proc = subprocess.run(
            ["say", "-v", "?"], check=False, capture_output=True, text=True
        )
    except OSError:
        return ""
    return (proc.stdout or "") + (proc.stderr or "")


def _not_tested(code: str, api_name: str, native_name: str,
                voice: str | None, reason: str) -> dict:
    return {
        "code": code,
        "api_name": api_name,
        "native_name": native_name,
        "voice": voice,
        "status": "not_tested",
        "reason": reason,
        "in_key": 4,
        "found": 0,
        "exact": 0,
        "flagged": 0,
        "wrong_unflagged": 0,
        "missed": 4,
        "cost_usd": 0.0,
        "seconds": 0.0,
    }


def _read_transcript_text(data_dir: Path, session_id: int) -> str:
    try:
        saved = json.loads(
            (data_dir / "sessions" / str(session_id) / "transcript.json")
            .read_text())
    except (OSError, ValueError):
        return ""
    if not isinstance(saved, dict):
        return ""
    return saved.get("text", "") or ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--provider", default="meta", choices=("meta", "baseten"))
    parser.add_argument("--from-json", action="store_true",
                        help="rebuild docs/languages.md from the saved JSON"
                             " without calling the network")
    args = parser.parse_args()
    if args.from_json:
        saved = json.loads(OUT_JSON.read_text())
        results = saved.get("results", [])
        DOC_PATH.write_text(render_languages_md(
            results, provider=saved.get("provider", "meta")))
        print(f"rebuilt {DOC_PATH} from {OUT_JSON} ({len(results)} languages)")
        return

    from app import db
    from app.config import load_settings
    from app.costs import CostCapExceeded, CostLedger
    from app.languages import get_language
    from app.pipeline.run import process_video_session

    only = {c.strip() for c in args.only.split(",") if c.strip()} or None

    os.environ["TEXT_PROVIDER"] = args.provider
    settings = load_settings()
    ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                        settings.daily_budget_usd)

    data = load_scripts()
    say_out = _say_output()
    codes = [c for c in sorted(data["languages"]) if not only or c in only]

    results: list[dict] = []
    capped = False
    for idx, code in enumerate(codes):
        entry = data["languages"][code]
        lang = get_language(code)
        voice = select_voice(say_out, entry["voice_locale"])
        if voice is None:
            results.append(_not_tested(
                code, lang.api_name, lang.native_name, None, "no test voice"))
            continue
        clip = CLIPS_DIR / f"{code}.mp4"
        answers_path = CLIPS_DIR / f"{code}.answers.json"
        if not clip.is_file() or not answers_path.is_file():
            results.append(_not_tested(
                code, lang.api_name, lang.native_name, voice, "no clip"))
            continue
        try:
            ledger.check()
        except CostCapExceeded:
            capped = True
            results.append(_not_tested(
                code, lang.api_name, lang.native_name, voice, "cost cap"))
            for rest in codes[idx + 1:]:
                rest_entry = data["languages"][rest]
                rest_lang = get_language(rest)
                rest_voice = select_voice(say_out, rest_entry["voice_locale"])
                results.append(_not_tested(
                    rest, rest_lang.api_name, rest_lang.native_name,
                    rest_voice, "cost cap" if rest_voice else "no test voice"))
            break
        conn = db.connect(Path(settings.data_dir))
        try:
            shop_id, _, _ = db.create_shop(
                conn, name=f"lang-{code}", phone="", area="demo",
                language=code, currency=lang.default_currency,
                shop_type="vegetable", is_demo=True)
            session_id = db.create_session(conn, shop_id, "video")
            spent_before = ledger.today_usd("meta")
            start = time.perf_counter()
            # The pipeline deletes the video it processes; work on a copy.
            with tempfile.TemporaryDirectory(prefix=f"langbench_{code}_") as tmp:
                src_copy = Path(tmp) / clip.name
                shutil.copy(clip, src_copy)
                process_video_session(conn, session_id, src_copy,
                                      settings=settings, ledger=ledger)
            seconds = time.perf_counter() - start
            run_usd = ledger.today_usd("meta") - spent_before
            out_items = [json.loads(db._draft_to_json(item))
                         for item in db.load_drafts(conn, session_id)]
            transcript_text = _read_transcript_text(
                Path(settings.data_dir), session_id)
        finally:
            conn.close()
        key = json.loads(answers_path.read_text())
        out = {"clip": clip.name, "items": out_items}
        scores = score_lang(key, out)
        results.append({
            "code": code,
            "api_name": lang.api_name,
            "native_name": lang.native_name,
            "voice": voice,
            "status": "tested",
            "in_key": scores["in_key"],
            "found": scores["found"],
            "exact": scores["exact"],
            "flagged": scores["flagged"],
            "wrong_unflagged": scores["wrong_unflagged"],
            "missed": scores["missed"],
            "cost_usd": round(run_usd, 4),
            "seconds": round(seconds, 1),
            "transcript": transcript_text,
            "items": detail_items(key, out),
        })
        try:
            ledger.check()
        except CostCapExceeded:
            capped = True
            for rest in codes[idx + 1:]:
                rest_entry = data["languages"][rest]
                rest_lang = get_language(rest)
                rest_voice = select_voice(say_out, rest_entry["voice_locale"])
                results.append(_not_tested(
                    rest, rest_lang.api_name, rest_lang.native_name,
                    rest_voice, "cost cap" if rest_voice else "no test voice"))
            break

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"provider": args.provider, "results": results}, indent=2))
    DOC_PATH.write_text(render_languages_md(results, provider=args.provider))
    print(f"wrote {OUT_JSON} and {DOC_PATH} "
          f"({len(results)} languages{' capped' if capped else ''})")


if __name__ == "__main__":
    main()
