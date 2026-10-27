"""Benchmark run outputs against answer keys.

Usage: .venv/bin/python scripts/benchmark.py [--provider baseten]
  [--out-dir eval/out] [--answers-dir eval/answers]

Compares eval/out/<clip>.json with eval/answers/<clip>.json, matching items by
name_en + variety (case-insensitive, bangalore == bengaluru) and prices by
rate. Prints a markdown table plus raised/missed expect_flags.
With --provider baseten, extraction reruns through Baseten into
eval/out/<clip>.baseten.json first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings
from app.costs import CostLedger
from app.models import PriceLine
from app.pipeline.extract import extract_items
from app.pipeline.run import _transcript_from_json
from app.pipeline.units import rate

_CANONICAL_VARIETY = {"bangalore": "bengaluru", "bengaluru": "bengaluru"}


def normalize_variety(variety) -> str | None:
    """Lowercased variety with bangalore/bengaluru unified; blank -> None."""
    if variety is None:
        return None
    text = str(variety).strip().lower()
    if not text:
        return None
    return _CANONICAL_VARIETY.get(text, text)


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def price_rate(price, per_amount, unit) -> tuple[Decimal, str] | None:
    return rate(PriceLine(_decimal(price), _decimal(per_amount), unit))


def _out_first_rate(out_item) -> tuple[Decimal, str] | None:
    for line in out_item.get("price_lines", []):
        result = price_rate(line.get("price"), line.get("per_amount"), line.get("unit"))
        if result is not None and line.get("price") is not None:
            return result
    return None


def _out_key(out_item) -> tuple[str, str | None]:
    return (str(out_item.get("name_en", "")).lower(),
            normalize_variety(out_item.get("variety")))


def compare_clips(key: dict, out: dict) -> dict:
    """Score one clip: exact prices, flagged vs unflagged misses, flag recall."""
    index: dict[tuple, dict] = {}
    for out_item in out.get("items", []):
        index.setdefault(_out_key(out_item), out_item)
    row: dict = {"clip": key.get("clip", ""), "in_key": 0, "found": 0,
                 "exact": 0, "flagged": 0, "unflagged": 0,
                 "raised": {}, "missed": {}}
    for key_item in key.get("items", []):
        row["in_key"] += 1
        expected = key_item.get("expect_flags", []) or []
        out_item = index.get((str(key_item.get("name_en", "")).lower(),
                              normalize_variety(key_item.get("variety"))))
        if out_item is None:
            for code in expected:
                row["missed"][code] = row["missed"].get(code, 0) + 1
            continue
        row["found"] += 1
        actual = [f.get("code") for f in out_item.get("flags", [])]
        for code in expected:
            if code in actual:
                row["raised"][code] = row["raised"].get(code, 0) + 1
            else:
                row["missed"][code] = row["missed"].get(code, 0) + 1
        want = price_rate(key_item.get("price"), key_item.get("per_amount"),
                          key_item.get("unit"))
        got = _out_first_rate(out_item)
        if want is not None and got is not None and want == got:
            row["exact"] += 1
        elif any(f.get("blocking", True) for f in out_item.get("flags", [])):
            row["flagged"] += 1
        else:
            row["unflagged"] += 1
    return row


def _table(rows: list[dict]) -> str:
    lines = ["| clip | in key | found | exact | wrong+flagged | wrong+unflagged |",
             "|---|---|---|---|---|---|"]
    totals = [0, 0, 0, 0, 0]
    for row in rows:
        lines.append(f"| {row['clip']} | {row['in_key']} | {row['found']} | "
                     f"{row['exact']} | {row['flagged']} | {row['unflagged']} |")
        for i, key in enumerate(("in_key", "found", "exact", "flagged", "unflagged")):
            totals[i] += row[key]
    lines.append(f"| TOTAL | {totals[0]} | {totals[1]} | {totals[2]} | "
                 f"{totals[3]} | {totals[4]} |")
    raised: dict[str, int] = {}
    missed: dict[str, int] = {}
    for row in rows:
        for code, count in row["raised"].items():
            raised[code] = raised.get(code, 0) + count
        for code, count in row["missed"].items():
            missed[code] = missed.get(code, 0) + count
    lines.append("")
    lines.append("expect_flags raised: " + (
        ", ".join(f"{c}×{n}" for c, n in sorted(raised.items())) or "(none)"))
    lines.append("expect_flags missed: " + (
        ", ".join(f"{c}×{n}" for c, n in sorted(missed.items())) or "(none)"))
    return "\n".join(lines)


def _rerun_baseten(out_path: Path) -> Path:
    """Rerun extraction only through Baseten; write <stem>.baseten.json."""
    out = json.loads(out_path.read_text())
    env = dict(os.environ)
    env["TEXT_PROVIDER"] = "baseten"
    settings = load_settings(env)
    ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                        settings.daily_budget_usd)
    transcript = _transcript_from_json(out["transcript"])
    items = extract_items(transcript, ledger=ledger, settings=settings)
    from scripts.run_clip import _draft_to_dict

    out = dict(out)
    out["items"] = [_draft_to_dict(item) for item in items]
    out["provider"] = "baseten"
    target = out_path.with_name(out_path.stem + ".baseten.json")
    target.write_text(json.dumps(out, indent=2))
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="meta")
    parser.add_argument("--out-dir", default="eval/out")
    parser.add_argument("--answers-dir", default="eval/answers")
    args = parser.parse_args()
    out_dir, answers_dir = Path(args.out_dir), Path(args.answers_dir)
    rows: list[dict] = []
    for key_path in sorted(answers_dir.glob("*.json")):
        out_path = out_dir / key_path.name
        if args.provider == "baseten":
            if not out_path.exists():
                print(f"skip {key_path.name}: no run output to rerun from")
                continue
            out_path = _rerun_baseten(out_path)
        if not out_path.exists():
            print(f"skip {key_path.name}: no run output")
            continue
        key = json.loads(key_path.read_text())
        out = json.loads(out_path.read_text())
        rows.append(compare_clips(key, out))
    print(_table(rows))


if __name__ == "__main__":
    main()
