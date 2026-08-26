#!/usr/bin/env python3
"""
Stage 1 territorial backtest for modello-uk.

Purpose
-------
Isolate the constituency conversion from polling error:
  2019 notional results on 2024 boundaries
  + ACTUAL 2024 GB national vote shares ("oracle" national target)
  -> projected 2024 constituency winners

This is deliberately NOT the final forecasting backtest. It tells us whether
the territorial seat conversion is defensible before historical polling is
added.

Source
------
UK Parliament / House of Commons Library psephology SQLite database:
https://github.com/ukparliament/psephology-datasette
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

DB_URL = "https://raw.githubusercontent.com/ukparliament/psephology-datasette/main/psephology.db"
OUT = DATA / "backtest-2024-territorial.json"

PARTIES = ("lab", "con", "ref", "ld", "green", "snp", "pc", "other")
MAIN_FLOOR = 0.18
SMALL_FLOOR = 0.03
CURRENT_LAMBDA = 0.82


def party_id(name: str | None, abbr: str | None, independent: int = 0, speaker: int = 0) -> str:
    n = (name or "").strip().lower()
    a = (abbr or "").strip().lower()

    if independent or speaker:
        return "other"
    if a in {"lab", "labour"} or "labour" in n:
        return "lab"
    if a in {"con", "cons"} or "conservative" in n:
        return "con"
    if a in {"ld", "lib dem", "libdem"} or "liberal democrat" in n:
        return "ld"
    if a in {"snp"} or "scottish national" in n:
        return "snp"
    if a in {"pc"} or "plaid cymru" in n:
        return "pc"
    if "green" in n or a in {"green", "grn"}:
        return "green"
    if (
        "reform uk" in n
        or "brexit party" in n
        or a in {"ref", "ruk", "brx", "brexit"}
    ):
        return "ref"
    return "other"


def download_db(dest: Path) -> None:
    with requests.get(DB_URL, timeout=90, stream=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    if dest.stat().st_size < 1_000_000:
        raise RuntimeError(f"Psephology database download is unexpectedly small: {dest.stat().st_size} bytes")


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def general_election_id(conn: sqlite3.Connection, date: str, notional: bool) -> int:
    rows = conn.execute(
        """
        SELECT id, polling_on, is_notional
        FROM general_elections
        WHERE polling_on = ? AND is_notional = ?
        ORDER BY id
        """,
        (date, int(notional)),
    ).fetchall()
    if len(rows) != 1:
        available = conn.execute(
            "SELECT id,polling_on,is_notional FROM general_elections ORDER BY polling_on,id"
        ).fetchall()
        raise RuntimeError(
            f"Expected one general election for {date} notional={notional}; "
            f"found {rows}. Available={available}"
        )
    return int(rows[0][0])


def election_rows(conn: sqlite3.Connection, ge_id: int) -> list[dict[str, Any]]:
    required = {
        "general_elections", "elections", "constituency_groups", "constituency_areas",
        "countries", "candidacies", "certifications", "political_parties"
    }
    found = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = required - found
    if missing:
        raise RuntimeError(f"Missing expected psephology tables: {sorted(missing)}")

    # Pick the primary (non-adjunct) party certification only. Labour/Co-op
    # candidacies, for example, should not be counted twice.
    sql = """
    SELECT
      ca.geographic_code AS code,
      ca.name AS constituency,
      co.name AS country,
      er.name AS region,
      cand.id AS candidacy_id,
      cand.vote_count AS votes,
      cand.is_winning_candidacy AS is_winner,
      cand.is_standing_as_independent AS is_independent,
      cand.is_standing_as_commons_speaker AS is_speaker,
      pp.name AS party_name,
      pp.abbreviation AS party_abbr
    FROM elections e
    JOIN constituency_groups cg
      ON cg.id = e.constituency_group_id
    JOIN constituency_areas ca
      ON ca.id = cg.constituency_area_id
    JOIN countries co
      ON co.id = ca.country_id
    LEFT JOIN english_regions er
      ON er.id = ca.english_region_id
    JOIN candidacies cand
      ON cand.election_id = e.id
    LEFT JOIN certifications cert
      ON cert.id = (
        SELECT c2.id
        FROM certifications c2
        WHERE c2.candidacy_id = cand.id
          AND c2.adjunct_to_certification_id IS NULL
        ORDER BY c2.id
        LIMIT 1
      )
    LEFT JOIN political_parties pp
      ON pp.id = cert.political_party_id
    WHERE e.general_election_id = ?
    ORDER BY ca.geographic_code, cand.vote_count DESC
    """
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, (ge_id,)).fetchall()]


def aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    seats: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        seat = seats.setdefault(code, {
            "id": code,
            "name": row.get("constituency") or code,
            "country": row.get("country") or "",
            "region": row.get("region") or row.get("country") or "",
            "votes": defaultdict(int),
            "winner": None,
        })
        pid = party_id(
            row.get("party_name"),
            row.get("party_abbr"),
            int(row.get("is_independent") or 0),
            int(row.get("is_speaker") or 0),
        )
        votes = int(row.get("votes") or 0)
        seat["votes"][pid] += votes
        if int(row.get("is_winner") or 0):
            seat["winner"] = pid

    for seat in seats.values():
        seat["votes"] = dict(seat["votes"])
        if not seat["winner"] and seat["votes"]:
            seat["winner"] = max(seat["votes"], key=seat["votes"].get)
    return seats


def national_shares(seats: dict[str, dict[str, Any]]) -> dict[str, float]:
    totals = Counter()
    for seat in seats.values():
        if "northern ireland" in seat["country"].lower():
            continue
        totals.update(seat["votes"])
    denom = sum(totals.values())
    if denom <= 0:
        raise RuntimeError("No GB votes found")
    return {p: totals[p] / denom * 100.0 for p in PARTIES}


def seat_shares(seat: dict[str, Any]) -> dict[str, float]:
    votes = seat["votes"]
    total = sum(votes.values())
    if total <= 0:
        return {p: 0.0 for p in PARTIES}
    return {p: votes.get(p, 0) / total * 100.0 for p in PARTIES}


def allowed(p: str, country: str) -> bool:
    c = country.lower()
    if p == "snp":
        return "scotland" in c
    if p == "pc":
        return "wales" in c
    return True


def project_seat(
    baseline: dict[str, Any],
    base_nat: dict[str, float],
    target_nat: dict[str, float],
    lam: float,
) -> str:
    base = seat_shares(baseline)
    raw: dict[str, float] = {}
    country = baseline["country"]

    for p in PARTIES:
        if not allowed(p, country):
            raw[p] = 0.0
            continue

        if p == "other":
            # "Other" is not a coherent national party. Keep its local 2019
            # baseline rather than imposing a national swing.
            raw[p] = max(base.get(p, 0.0), SMALL_FLOOR)
            continue

        floor = MAIN_FLOOR if p in {"lab", "con", "ref", "ld", "green"} else SMALL_FLOOR
        b = max(base.get(p, 0.0), floor)
        bn = max(base_nat.get(p, 0.0), 0.05)
        tn = max(target_nat.get(p, 0.0), 0.05)
        ratio = max(0.08, tn / bn)
        raw[p] = b * (ratio ** lam)

    return max(raw, key=raw.get)


def evaluate(
    baseline: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
    base_nat: dict[str, float],
    target_nat: dict[str, float],
    lam: float,
) -> dict[str, Any]:
    pred = Counter()
    real = Counter()
    correct = 0
    n = 0
    by_region: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    missing = []
    for code, a in actual.items():
        if "northern ireland" in a["country"].lower():
            continue
        b = baseline.get(code)
        if not b:
            missing.append(code)
            continue
        pw = project_seat(b, base_nat, target_nat, lam)
        rw = a["winner"] or "other"
        pred[pw] += 1
        real[rw] += 1
        n += 1
        if pw == rw:
            correct += 1
            by_region[a["region"]][0] += 1
        by_region[a["region"]][1] += 1

    if missing:
        raise RuntimeError(f"{len(missing)} actual GB constituencies missing from 2019 notional baseline: {missing[:10]}")
    if n != 632:
        raise RuntimeError(f"Expected 632 GB seats in backtest, got {n}")

    seat_errors = {p: int(pred[p] - real[p]) for p in PARTIES}
    abs_error = sum(abs(v) for v in seat_errors.values())
    mae = abs_error / len(PARTIES)

    return {
        "lambda": round(lam, 3),
        "winner_accuracy": correct / n,
        "correct_winners": correct,
        "gb_seats": n,
        "predicted_seats": {p: int(pred[p]) for p in PARTIES},
        "actual_seats": {p: int(real[p]) for p in PARTIES},
        "seat_error": seat_errors,
        "seat_abs_error_sum": int(abs_error),
        "seat_mae_across_party_buckets": mae,
        "regional_accuracy": {
            region: {
                "correct": vals[0],
                "n": vals[1],
                "accuracy": vals[0] / vals[1] if vals[1] else None,
            }
            for region, vals in sorted(by_region.items())
        },
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "psephology.db"
        print("Downloading UK Parliament psephology database...")
        download_db(db_path)

        conn = sqlite3.connect(db_path)
        try:
            actual_2024_id = general_election_id(conn, "2024-07-04", False)
            notional_2019_id = general_election_id(conn, "2019-12-12", True)

            actual = aggregate(election_rows(conn, actual_2024_id))
            baseline = aggregate(election_rows(conn, notional_2019_id))

            if len(actual) != 650:
                raise RuntimeError(f"Expected 650 constituencies in 2024 actual, got {len(actual)}")
            if len(baseline) != 650:
                raise RuntimeError(f"Expected 650 constituencies in 2019 notional, got {len(baseline)}")

            base_nat = national_shares(baseline)
            target_nat = national_shares(actual)

            grid = []
            x = 0.40
            while x <= 1.200001:
                grid.append(evaluate(baseline, actual, base_nat, target_nat, round(x, 2)))
                x += 0.02

            current = evaluate(baseline, actual, base_nat, target_nat, CURRENT_LAMBDA)

            # Primary criterion: constituency winner accuracy.
            # Tie-break: lower aggregate absolute seat error.
            best = sorted(
                grid,
                key=lambda r: (-r["winner_accuracy"], r["seat_abs_error_sum"], abs(r["lambda"] - CURRENT_LAMBDA)),
            )[0]

            payload = {
                "meta": {
                    "stage": 1,
                    "label": "territorial conversion / oracle national vote",
                    "source": "UK Parliament psephology database",
                    "source_db": DB_URL,
                    "baseline": "2019 notional results on 2024 boundaries",
                    "target": "2024 actual result",
                    "important": (
                        "This isolates constituency conversion from polling error. "
                        "It is not a full historical forecast backtest and must not be used "
                        "alone to choose the final production model."
                    ),
                },
                "national_2019_notional_gb": {k: round(v, 4) for k, v in base_nat.items()},
                "national_2024_actual_gb": {k: round(v, 4) for k, v in target_nat.items()},
                "current_lambda_0_82": current,
                "best_lambda_by_winner_accuracy": best,
                "grid": grid,
            }

            OUT.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"Wrote {OUT.relative_to(ROOT)}")
            print(
                "Current λ=0.82:",
                f"winner accuracy={current['winner_accuracy']:.3%},",
                f"abs seat error={current['seat_abs_error_sum']}"
            )
            print(
                f"Best grid λ={best['lambda']:.2f}:",
                f"winner accuracy={best['winner_accuracy']:.3%},",
                f"abs seat error={best['seat_abs_error_sum']}"
            )
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"build_backtest.py failed: {exc}", file=sys.stderr)
        raise
