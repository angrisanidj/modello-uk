#!/usr/bin/env python3
"""Replay the frozen stack with retained inputs; never deploy or promote."""
import copy
import hashlib
import json
import statistics
from datetime import datetime
from pathlib import Path

import build_data
import build_mrp_geography_bridge as bridge
import build_mrp_lite as core
import promote_mrp_stack as promotion

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'diagnostics'
OUT.mkdir(exist_ok=True)
POLL_PATH = ROOT / 'data/polls.json'
FIXED = datetime.fromisoformat('2026-10-25T09:51:19+00:00')
PREVIOUS = datetime.fromisoformat('2026-10-25T04:28:14+00:00')


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def margin(seat):
    shares = seat['projected']
    winner = seat['centralWinner']
    eligible = {p: float(v) for p, v in shares.items()
                if p != 'other' or seat.get('otherEligible') is True}
    return eligible[winner] - max(v for p, v in eligible.items() if p != winner)


def describe(scenarios):
    main = {s['id']: s for s in scenarios['precision_freshness_primary']['seats']}
    out = {}
    for key, payload in scenarios.items():
        if key == 'precision_freshness_primary':
            continue
        changed = []
        for alt in payload['seats']:
            primary = main[alt['id']]
            if primary['centralWinner'] != alt['centralWinner']:
                changed.append({'id': alt['id'], 'name': alt['name'],
                                'primary': primary['centralWinner'], 'alternative': alt['centralWinner'],
                                'primary_margin_pp': round(margin(primary), 5),
                                'alternative_margin_pp': round(margin(alt), 5),
                                'primary_projected': primary['projected'], 'alternative_projected': alt['projected']})
        margins = [x['primary_margin_pp'] for x in changed]
        out[key] = {'changed_winners': len(changed), 'totals': payload['totals'],
                    'primary_margin_median_pp': statistics.median(margins) if margins else 0,
                    'primary_margin_max_pp': max(margins, default=0),
                    'primary_margin_le_1pp': sum(x <= 1 for x in margins),
                    'primary_margin_le_2pp': sum(x <= 2 for x in margins),
                    'primary_margin_gt_5pp': sum(x > 5 for x in margins),
                    'changed_seats': changed}
    return out


def target(payload, when):
    POLL_PATH.write_text(json.dumps(payload))
    core.utcnow = lambda: when
    return core.calculate_poll_target(POLL_PATH)


def main():
    old = json.loads(POLL_PATH.read_text())
    new = {'meta': {'source': 'Wikipedia / MediaWiki API', 'diagnostic_fetch': True},
           'polls': build_data.fetch_polls()}
    write('polls-reference.json', old)
    write('polls-refreshed.json', new)
    encode = lambda p: json.dumps(p, sort_keys=True)
    old_set = {encode(p) for p in old['polls']}
    new_set = {encode(p) for p in new['polls']}
    input_diff = {'added_or_modified': [json.loads(p) for p in sorted(new_set-old_set)],
                  'removed_or_modified': [json.loads(p) for p in sorted(old_set-new_set)],
                  'reference_target_original_time': target(old, PREVIOUS),
                  'reference_target_failed_time': target(old, FIXED),
                  'refreshed_target_failed_time': target(new, FIXED)}
    write('input-comparison.json', input_diff)
    print('INPUT_COMPARISON', json.dumps(input_diff, ensure_ascii=False), flush=True)
    original = bridge._projection_stability
    summaries = {}
    for label, polls in [('reference', old), ('refreshed', new)]:
        POLL_PATH.write_text(json.dumps(polls))
        core.utcnow = lambda: FIXED
        captured = {}
        def capture(scenarios):
            captured.update(copy.deepcopy(scenarios))
            return original(scenarios)
        bridge._projection_stability = capture
        bridge.main()
        details = describe(captured)
        candidate = json.loads(bridge.LIVE_OUT.read_text())
        backtest = json.loads(bridge.BACKTEST_OUT.read_text())
        integrity = json.loads(bridge.INTEGRITY_OUT.read_text())
        audit = promotion.validate_candidate(candidate, backtest, integrity)
        write(label+'-scenarios.json', captured)
        write(label+'-details.json', details)
        write(label+'-candidate.json', candidate)
        write(label+'-audit.json', audit)
        write(label+'-source-meta.json', candidate.get('source_meta'))
        summaries[label] = {key: {k:v for k,v in stats.items() if k!='changed_seats'} for key,stats in details.items()}
        print('SCENARIO_SUMMARY', label, json.dumps(summaries[label]), flush=True)
        print('PROMOTION_AUDIT', label, json.dumps(audit), flush=True)
    write('summary.json', summaries)
    ref = json.loads((OUT/'reference-details.json').read_text())['direct_mic26']['changed_seats']
    cur = json.loads((OUT/'refreshed-details.json').read_text())['direct_mic26']['changed_seats']
    ref_ids = {s['id'] for s in ref}
    cur_ids = {s['id'] for s in cur}
    print('NEW_DISAGREEMENTS', json.dumps([s for s in cur if s['id'] not in ref_ids]), flush=True)
    print('RESOLVED_DISAGREEMENTS', json.dumps([s for s in ref if s['id'] not in cur_ids]), flush=True)
    write('hashes.json', {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                         for folder in (ROOT/'data', ROOT/'.cache') for p in folder.rglob('*') if p.is_file()})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
