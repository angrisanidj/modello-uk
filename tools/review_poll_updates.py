#!/usr/bin/env python3
"""Lightweight polling-source review for modello-UK.

Checks national and Scotland/Wales Westminster polling feeds against the
committed snapshots without rewriting data files.  A separate workflow can
then trigger the full production build only when the polling content changed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from build_data import DATA, fetch_polls, fetch_subnational_polls


def _load_poll_rows(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    rows = payload.get("polls", []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def _latest_date(rows: list[dict]) -> str:
    dates = [str(row.get("date") or "") for row in rows if isinstance(row, dict)]
    return max(dates, default="")

def _canonical_rows(rows: list[dict]) -> list[str]:
    """Compare poll content independent of source ordering."""
    return sorted(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
        if isinstance(row, dict)
    )


def _write_github_output(path: str | None, values: dict[str, str]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()

    old_national = _load_poll_rows(DATA / "polls.json")
    old_subnational = _load_poll_rows(DATA / "subnational-polls.json")
    new_national = fetch_polls()
    new_subnational = fetch_subnational_polls()

    national_changed = _canonical_rows(new_national) != _canonical_rows(old_national)
    subnational_changed = _canonical_rows(new_subnational) != _canonical_rows(old_subnational)
    changed = national_changed or subnational_changed

    summary = {
        "changed": changed,
        "national_changed": national_changed,
        "subnational_changed": subnational_changed,
        "national_rows_before": len(old_national),
        "national_rows_now": len(new_national),
        "subnational_rows_before": len(old_subnational),
        "subnational_rows_now": len(new_subnational),
        "latest_national_before": _latest_date(old_national),
        "latest_national_now": _latest_date(new_national),
        "latest_subnational_before": _latest_date(old_subnational),
        "latest_subnational_now": _latest_date(new_subnational),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _write_github_output(args.github_output, {
        "changed": str(changed).lower(),
        "national_changed": str(national_changed).lower(),
        "subnational_changed": str(subnational_changed).lower(),
        "latest_national": summary["latest_national_now"],
        "latest_subnational": summary["latest_subnational_now"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
