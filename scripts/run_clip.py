"""Run the pipeline on a clip without the web app.

Usage: .venv/bin/python scripts/run_clip.py eval/clips/synth1.mp4
Writes eval/out/<stem>.json and prints the Meta spend for the run.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from app import db
from app.config import load_settings
from app.costs import CostLedger
from app.pipeline.run import process_video_session


def _draft_to_dict(item) -> dict:
    return json.loads(db._draft_to_json(item))


def main() -> None:
    clip = Path(sys.argv[1])
    settings = load_settings()
    ledger = CostLedger(Path(settings.data_dir) / "costs.db", settings.daily_budget_usd)
    conn = db.connect(Path(settings.data_dir))
    try:
        shop_id, _, _ = db.create_shop(
            conn, name=clip.stem, phone="", area="demo", language="ta",
            currency="INR", shop_type="vegetable", is_demo=True)
        session_id = db.create_session(conn, shop_id, "video")
        spent_before = ledger.today_usd("meta")
        # The pipeline deletes the video it processes; work on a temp copy so
        # the owner's clip (e.g. an eval asset) is never destroyed.
        with tempfile.TemporaryDirectory(prefix="run_clip_") as tmp:
            src_copy = Path(tmp) / clip.name
            shutil.copy(clip, src_copy)
            process_video_session(conn, session_id, src_copy,
                                  settings=settings, ledger=ledger)
        run_usd = ledger.today_usd("meta") - spent_before
        row = conn.execute("SELECT status, message FROM sessions WHERE id = ?",
                           (session_id,)).fetchone()
        transcript_path = (Path(settings.data_dir) / "sessions" / str(session_id)
                           / "transcript.json")
        transcript = json.loads(transcript_path.read_text()) if transcript_path.exists() else None
        out = {
            "clip": clip.name,
            "shop_id": shop_id,
            "session_id": session_id,
            "status": row["status"],
            "message": row["message"],
            "transcript": transcript,
            "items": [_draft_to_dict(item) for item in db.load_drafts(conn, session_id)],
            "meta_usd": round(run_usd, 4),
        }
        out_path = Path("eval/out") / (clip.stem + ".json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2))
        print(f"clip={clip.name} status={row['status']} "
              f"items={len(out['items'])} meta_usd={out['meta_usd']:.4f}")
        print(f"wrote {out_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
