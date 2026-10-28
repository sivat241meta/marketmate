"""Benchmark the pipeline on the synthetic language clips.

Usage: .venv/bin/python scripts/lang_benchmark.py [--only ta,hi,...]
       [--provider meta|baseten]

For each language in eval/lang/scripts.json with a macOS test voice and a
built clip (see scripts/make_lang_clips.py), creates a temporary shop with
that language code, runs the normal pipeline
(app.pipeline.run.process_video_session) on eval/clips/lang/{code}.mp4,
scores with scripts.benchmark.compare_clips, and records Meta cost from
the ledger plus seconds.

Writes eval/out/lang_results.json and regenerates docs/languages.md.
Stops early if the daily cost cap is hit, keeping partial results.
The owner's reviewer runs this live (it calls the network).
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.benchmark import compare_clips
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


def notes_for(result: dict) -> str:
    """Table notes; never claims an untested or wrong language works."""
    if result.get("status") == "not_tested":
        reason = result.get("reason", "no test voice") or "no test voice"
        if reason == "no test voice":
            return "not tested (no test voice)"
        return f"not tested ({reason})"
    if result.get("wrong_unflagged", 0) > 0:
        return "needs work"
    if result.get("found", 0) < 4 or result.get("exact", 0) < 4:
        return "needs work"
    return "ok"


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
    needy = [r for r in tested if notes_for(r) == "needs work"]
    untested = [r for r in results if r.get("status") == "not_tested"]
    lines += [
        "",
        (
            f"Summary: tested {len(tested)} of {len(results)} languages; "
            f"{len(perfect)} reached 4/4 exact with no wrong-unflagged; "
            f"{len(needy)} need work; "
            f"{len(untested)} not tested (no test voice or no clip)."
        ),
        "",
    ]
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


def main() -> None:
    from app import db
    from app.config import load_settings
    from app.costs import CostCapExceeded, CostLedger
    from app.languages import get_language
    from app.pipeline.run import process_video_session

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--provider", default="meta", choices=("meta", "baseten"))
    args = parser.parse_args()
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
        finally:
            conn.close()
        key = json.loads(answers_path.read_text())
        scores = score_lang(key, {"clip": clip.name, "items": out_items})
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
