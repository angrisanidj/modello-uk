#!/usr/bin/env python3
"""
modello-UK v0.9.29 — audited production promotion for the v0.9.28 MRP stack.

This file does NOT fit or tune the statistical model.  It is a governance layer:
- consumes the already-generated v0.9.28 shadow candidate and backtest;
- enforces frozen historical and cross-validation gates;
- checks 2026 source completeness / sensitivity diagnostics;
- writes data/mrp-lite-live.json only when every promotion gate passes.

The underlying constituency geography and provider weights remain exactly those generated
by v0.9.28.  No 2026 election outcome exists or is consulted.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CANDIDATE_PATH = DATA / "mrp-lite-live-v0928-candidate.json"
BACKTEST_PATH = DATA / "backtest-v0928-geography-stack.json"
INTEGRITY_PATH = DATA / "bes-integrity-v0928.json"
PRODUCTION_PATH = DATA / "mrp-lite-live.json"
AUDIT_PATH = DATA / "promotion-audit-v0929.json"

V0929_PROMOTION = "audited-v0928-precision-stack-to-production"
V0929_MODEL_FREEZE = "no-statistical-retuning-during-promotion"
V0929_PRODUCTION_SCHEMA = "precision-weighted-contemporary-mrp-geography-v1"
V0929_STABILITY_POLICY = "core-contemporary-scenarios-max-75-changed-winners"

PARTIES = ("lab", "con", "ref", "ld", "green", "snp", "pc", "other")
CORE_SENSITIVITY_KEYS = ("skill_only_stack", "equal_provider_stack", "direct_mic26")
MAX_CORE_CHANGED_WINNERS = 75


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_candidate(candidate: dict[str, Any], backtest: dict[str, Any], integrity: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if candidate.get("version") != "uk-v0928-mrp-geography-stack-live-candidate" or candidate.get("status") != "ok":
        _fail(errors, f"unexpected candidate identity/status: {candidate.get('version')} / {candidate.get('status')}")
    if backtest.get("version") != "uk-v0928-mrp-geography-stack" or backtest.get("status") != "ok":
        _fail(errors, f"unexpected backtest identity/status: {backtest.get('version')} / {backtest.get('status')}")
    if integrity.get("version") != "uk-v0928-bes-integrity-wrapper" or integrity.get("status") != "passed":
        _fail(errors, f"BES integrity not passed: {integrity.get('status')} {integrity.get('errors')}")

    # Ensure the source object is still genuinely shadow-only before promotion.
    if candidate.get("approved_for_live") is not False or candidate.get("applied_to_production") is not False:
        _fail(errors, "v0.9.28 candidate was already promoted or approval state changed")
    if candidate.get("provider_topline_used") is not False:
        _fail(errors, "external provider topline entered candidate")
    if candidate.get("uses_2024_for_geography_strength_selection") is not False:
        _fail(errors, "2024 leaked into historical geography-strength selection")
    if candidate.get("uses_2024_for_live_provider_reliability") is not True:
        _fail(errors, "2024 provider-reliability training disclosure missing")

    # Frozen historical breakthrough.
    selected = backtest.get("strength_selection_2019", {}).get("selected", {})
    primary = backtest.get("benchmark_2024", {}).get("primary_yougov_anchor", {})
    if selected.get("correct_winners") != 609 or selected.get("seat_abs_error_sum") != 14:
        _fail(errors, f"2019 frozen result regressed: {selected}")
    if primary.get("correct_winners") != 578 or primary.get("seat_abs_error_sum") != 56:
        _fail(errors, f"2024 frozen YouGov benchmark regressed: {primary}")
    if round(float(backtest.get("selected_strength", -1)), 3) != 0.875:
        _fail(errors, f"frozen geography strength changed: {backtest.get('selected_strength')}")

    # Cross-validated live provider stack.
    cv = backtest.get("live_provider_stack_training_2024", {}).get("leave_one_region_out", {})
    cvm = cv.get("metrics", {})
    if cv.get("passes_no_regression_vs_yougov_anchor") is not True:
        _fail(errors, "provider-stack leave-one-region-out no-regression gate failed")
    if cv.get("uses_held_out_region_outcome_for_its_weights") is not False:
        _fail(errors, "held-out region outcome leaked into its provider weights")
    if cvm.get("correct_winners") != 584 or cvm.get("seat_abs_error_sum") != 44:
        _fail(errors, f"cross-validated provider stack changed: {cvm}")
    folds = cv.get("folds", [])
    if len(folds) < 10 or sum(int(x.get("test_seats", 0)) for x in folds) != 632:
        _fail(errors, "leave-one-region-out folds incomplete")

    # Source / parser completeness.
    live_geo = candidate.get("live_geography", {})
    if live_geo.get("status") != "precision_weighted_yougov24_plus_direct_mic26":
        _fail(errors, f"unexpected live geography: {live_geo.get('status')}")
    if live_geo.get("provider_toplines_used") is not False:
        _fail(errors, "live geography used provider toplines")
    weights = live_geo.get("current_provider_weights_by_party", {})
    if set(weights) != set(PARTIES) or any(not (0.0 <= float(v) <= 1.0) for v in weights.values()):
        _fail(errors, f"invalid provider weights: {weights}")

    source_meta = candidate.get("source_meta", {}).get("mic2026", {})
    required = set(PARTIES)
    if set(source_meta.get("mapped_columns", {})) != required:
        _fail(errors, f"MiC 2026 party columns incomplete: {source_meta.get('mapped_columns')}")
    if int(source_meta.get("rows", 0)) < 620:
        _fail(errors, f"MiC 2026 constituency coverage too low: {source_meta.get('rows')}")

    # Structural seat payload checks.
    seats = candidate.get("seats", [])
    if len(seats) != 632:
        _fail(errors, f"candidate has {len(seats)} GB seats, expected 632")
    ids: set[str] = set()
    bad_sums = []
    bad_geo = []
    for seat in seats:
        sid = str(seat.get("id", ""))
        if not sid or sid in ids:
            _fail(errors, f"missing/duplicate constituency id: {sid!r}")
            continue
        ids.add(sid)
        projected = seat.get("projected", {})
        vals = []
        for p in PARTIES:
            v = projected.get(p, 0.0)
            try:
                fv = float(v)
            except Exception:
                fv = float("nan")
            if not math.isfinite(fv) or fv < -1e-8:
                _fail(errors, f"invalid projected share {sid} {p}={v!r}")
            vals.append(max(0.0, fv if math.isfinite(fv) else 0.0))
        if abs(sum(vals) - 100.0) > 0.08:
            bad_sums.append((sid, sum(vals)))
        country = str(seat.get("country", ""))
        if country != "Scotland" and float(projected.get("snp", 0) or 0) > 1e-6:
            bad_geo.append((sid, "snp", country))
        if country != "Wales" and float(projected.get("pc", 0) or 0) > 1e-6:
            bad_geo.append((sid, "pc", country))
    if bad_sums:
        _fail(errors, f"{len(bad_sums)} constituency rows do not sum to 100; sample={bad_sums[:5]}")
    if bad_geo:
        _fail(errors, f"party geography violations; sample={bad_geo[:5]}")

    target = candidate.get("target_gb", {})
    if set(target) != set(PARTIES) or abs(sum(float(target[p]) for p in PARTIES) - 100.0) > 0.05:
        _fail(errors, f"invalid internal GB target: {target}")

    # Governance-only robustness gate.  This does not tune any weight: it merely
    # requires the chosen primary to keep >= ~88% of winners stable against each
    # contemporary sensitivity route (75 / 632 maximum disagreement).
    changed = candidate.get("live_2026_sensitivity", {}).get("changed_winners_vs_primary", {})
    core_changed = {k: int(changed.get(k, 10**9)) for k in CORE_SENSITIVITY_KEYS}
    if any(v > MAX_CORE_CHANGED_WINNERS for v in core_changed.values()):
        _fail(errors, f"2026 core-sensitivity stability gate failed: {core_changed}")
    if any(v > 60 for v in core_changed.values()):
        warnings.append(f"one or more core contemporary alternatives differ in >60 seats: {core_changed}")

    passed = not errors
    return {
        "version": "uk-v0929-production-promotion-audit",
        "status": "passed" if passed else "failed",
        "generated_at": utcnow(),
        "promotion_marker": V0929_PROMOTION,
        "model_freeze": V0929_MODEL_FREEZE,
        "production_schema": V0929_PRODUCTION_SCHEMA,
        "statistical_engine_source": "v0.9.28 precision-weighted contemporary MRP stack",
        "statistical_retraining_in_v0929": False,
        "gates": {
            "frozen_2019": {"correct_winners": selected.get("correct_winners"), "seat_abs_error_sum": selected.get("seat_abs_error_sum"), "passed": selected.get("correct_winners") == 609 and selected.get("seat_abs_error_sum") == 14},
            "frozen_2024_yougov_benchmark": {"correct_winners": primary.get("correct_winners"), "seat_abs_error_sum": primary.get("seat_abs_error_sum"), "passed": primary.get("correct_winners") == 578 and primary.get("seat_abs_error_sum") == 56},
            "provider_stack_2024_leave_region_out": {"correct_winners": cvm.get("correct_winners"), "seat_abs_error_sum": cvm.get("seat_abs_error_sum"), "passed": bool(cv.get("passes_no_regression_vs_yougov_anchor"))},
            "provider_topline_excluded": candidate.get("provider_topline_used") is False,
            "candidate_seat_count": len(seats),
            "internal_target_sum": sum(float(target.get(p, 0)) for p in PARTIES),
            "core_2026_changed_winners_vs_primary": core_changed,
            "core_2026_max_changed_winners_allowed": MAX_CORE_CHANGED_WINNERS,
            "core_2026_stability_passed": all(v <= MAX_CORE_CHANGED_WINNERS for v in core_changed.values()),
        },
        "warnings": warnings,
        "errors": errors,
    }


def build_production(candidate: dict[str, Any], backtest: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    if audit.get("status") != "passed":
        raise RuntimeError(f"promotion audit failed: {audit.get('errors')}")
    out = copy.deepcopy(candidate)
    selected = backtest["strength_selection_2019"]["selected"]
    primary = backtest["benchmark_2024"]["primary_yougov_anchor"]
    cvm = backtest["live_provider_stack_training_2024"]["leave_one_region_out"]["metrics"]
    out.update({
        "version": "uk-v0929-precision-weighted-mrp-live",
        "model_type": V0929_PRODUCTION_SCHEMA,
        "status": "ok",
        "approved": True,
        "approved_for_live": True,
        "publication_ready": True,
        "diagnostic_only": False,
        "shadow_only": False,
        "live_candidate": False,
        "applied_to_production": True,
        "changes_production_model": True,
        "source_candidate_version": candidate.get("version"),
        "production_promotion_version": "v0.9.29",
        "promoted_at": utcnow(),
        "holdout_accuracy": float(primary["winner_accuracy"]),  # compatibility field; see benchmark_label
        "holdout_seat_abs_error": int(primary["seat_abs_error_sum"]),
        "benchmark_label": "2024 development benchmark, pre-election YouGov geography; not a pristine holdout",
        "validation_2019_accuracy": float(selected["winner_accuracy"]),
        "validation_2019_correct_winners": int(selected["correct_winners"]),
        "validation_2019_seat_abs_error": int(selected["seat_abs_error_sum"]),
        "provider_stack_cv_2024_accuracy": float(cvm["winner_accuracy"]),
        "provider_stack_cv_2024_correct_winners": int(cvm["correct_winners"]),
        "provider_stack_cv_2024_seat_abs_error": int(cvm["seat_abs_error_sum"]),
        "provider_stack_cv_label": "leave-one-region-out historical validation of provider reliability on 2024",
        "selected_spec": {"name": "precision-weighted YouGov-2024 + direct MiC-2026 geography, freshness-adjusted, strength 0.875"},
        "promotion_audit": {
            "version": audit.get("version"),
            "status": audit.get("status"),
            "path": "data/promotion-audit-v0929.json",
            "statistical_retraining_in_v0929": False,
            "core_2026_stability_policy": V0929_STABILITY_POLICY,
        },
    })
    return out


def _self_test() -> int:
    # Minimal but structurally complete synthetic payload: validates that the
    # promotion layer itself neither fits nor mutates constituency projections.
    parties = {p: 12.5 for p in PARTIES}
    parties.update({"snp": 0.0, "pc": 0.0})
    # For England sum back to 100 without SNP/PC.
    eng = {"lab": 20.0, "con": 20.0, "ref": 20.0, "ld": 15.0, "green": 15.0, "snp": 0.0, "pc": 0.0, "other": 10.0}
    seats = [{"id": f"E{i:08d}", "country": "England", "projected": dict(eng), "centralWinner": "lab", "otherEligible": False} for i in range(632)]
    candidate = {
        "version": "uk-v0928-mrp-geography-stack-live-candidate", "status": "ok",
        "approved_for_live": False, "applied_to_production": False,
        "provider_topline_used": False, "uses_2024_for_geography_strength_selection": False,
        "uses_2024_for_live_provider_reliability": True,
        "live_geography": {"status": "precision_weighted_yougov24_plus_direct_mic26", "provider_toplines_used": False, "current_provider_weights_by_party": {p: 0.5 for p in PARTIES}},
        "source_meta": {"mic2026": {"mapped_columns": {p: p for p in PARTIES}, "rows": 631}},
        "seats": seats, "target_gb": {p: 12.5 for p in PARTIES},
        "live_2026_sensitivity": {"changed_winners_vs_primary": {"skill_only_stack": 40, "equal_provider_stack": 30, "direct_mic26": 48}},
    }
    folds = [{"test_seats": 58} for _ in range(10)] + [{"test_seats": 52}]
    # 10*58 + 52 = 632
    backtest = {
        "version": "uk-v0928-mrp-geography-stack", "status": "ok", "selected_strength": 0.875,
        "strength_selection_2019": {"selected": {"correct_winners": 609, "seat_abs_error_sum": 14, "winner_accuracy": 609/632}},
        "benchmark_2024": {"primary_yougov_anchor": {"correct_winners": 578, "seat_abs_error_sum": 56, "winner_accuracy": 578/632}},
        "live_provider_stack_training_2024": {"leave_one_region_out": {"passes_no_regression_vs_yougov_anchor": True, "uses_held_out_region_outcome_for_its_weights": False, "folds": folds, "metrics": {"correct_winners": 584, "seat_abs_error_sum": 44, "winner_accuracy": 584/632}}},
    }
    integrity = {"version": "uk-v0928-bes-integrity-wrapper", "status": "passed"}
    audit = validate_candidate(candidate, backtest, integrity)
    if audit["status"] != "passed":
        raise RuntimeError(f"synthetic promotion audit failed: {audit}")
    prod = build_production(candidate, backtest, audit)
    if not (prod.get("approved") is True and prod.get("applied_to_production") is True and len(prod.get("seats", [])) == 632):
        raise RuntimeError("production schema self-test failed")
    if prod["seats"] != candidate["seats"]:
        raise RuntimeError("promotion layer mutated constituency projections")
    print("v0.9.29 promotion self-test: PASSED")
    return 0


def main() -> int:
    candidate = load_json(CANDIDATE_PATH)
    backtest = load_json(BACKTEST_PATH)
    integrity = load_json(INTEGRITY_PATH)
    audit = validate_candidate(candidate, backtest, integrity)
    write_json(AUDIT_PATH, audit)
    if audit["status"] != "passed":
        raise SystemExit(f"v0.9.29 promotion audit FAILED: {audit['errors']}")
    production = build_production(candidate, backtest, audit)
    write_json(PRODUCTION_PATH, production)
    print("v0.9.29 production promotion: PASSED")
    print("2019:", production["validation_2019_correct_winners"], "/632, seat error", production["validation_2019_seat_abs_error"])
    print("2024 primary:", round(production["holdout_accuracy"]*100, 2), "% | stack CV:", round(production["provider_stack_cv_2024_accuracy"]*100, 2), "%")
    print("2026 central GB totals:", production.get("totals", {}))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    raise SystemExit(_self_test() if args.self_test else main())
