"""Analyse a stall photo live: products, SAM counts, suggestions.

Usage: .venv/bin/python scripts/run_photo.py PATH [--shop-items tomato,onion]

Needs the network (Muse Spark + SAM). Prints the report; use --shop-items to
name the items already on the shop's price list.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import load_settings
from app.costs import CostLedger
from app.pipeline.vision import analyse_photo


def _shop_items(argv: list[str]) -> list[dict]:
    names: list[str] = []
    for index, arg in enumerate(argv):
        if arg == "--shop-items" and index + 1 < len(argv):
            names = argv[index + 1].split(",")
        elif arg.startswith("--shop-items="):
            names = arg.split("=", 1)[1].split(",")
    return [{"name_en": name.strip().lower(), "sold_out": False}
            for name in names if name.strip()]


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
        print(__doc__.strip().splitlines()[3])
        raise SystemExit(2)
    image = Path(sys.argv[1])
    if not image.is_file():
        print(f"no such file: {image}")
        raise SystemExit(2)
    settings = load_settings()
    ledger = CostLedger(Path(settings.data_dir) / "costs.db",
                        settings.daily_budget_usd)
    report = analyse_photo(image, shop_items=_shop_items(sys.argv[2:]),
                           ledger=ledger, settings=settings)
    print(f"photo quality: {report.quality}")
    for product in report.products:
        if product.needs_check and product.count_range is not None:
            low, high = product.count_range
            count = f"between {low} and {high}, please check"
        elif product.count is not None:
            count = f"about {product.count} visible"
        else:
            count = "not countable"
        print(f"- {product.name_en}: spark={product.count_spark}"
              f" sam={product.count_sam} -> {count}"
              f" boxes={len(product.boxes)}"
              f" condition={product.condition or '-'}")
    print("suggestions:")
    for suggestion in report.suggestions:
        print(f"- [{suggestion.kind}] {suggestion.text}")
    print(f"cost_usd={report.cost_usd:.4f}")


if __name__ == "__main__":
    main()
