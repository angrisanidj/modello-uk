#!/usr/bin/env python3
"""Identify retained outputs without treating older checked-in files as fresh."""
import hashlib
import json
import os
from pathlib import Path
import sys

PRODUCERS = {
    'data/polls.json': 'refresh_data',
    'data/build-meta.json': 'refresh_data',
    'data/mrp-lite-live-v0928-candidate.json': 'build_candidate',
    'data/backtest-v0928-geography-stack.json': 'build_candidate',
    'data/bes-integrity-v0928.json': 'build_candidate',
    'data/mrp-geography-stack-v0928.json': 'build_candidate',
    'data/promotion-audit-v0929.json': 'promote_model',
}


def capture(root):
    rows = {}
    for name in PRODUCERS:
        path = root / name
        row = {'exists': path.is_file()}
        if row['exists']:
            raw = path.read_bytes()
            row['sha256'] = hashlib.sha256(raw).hexdigest()
            try:
                payload = json.loads(raw)
                row['generated_at'] = payload.get('generated_at') or payload.get('meta', {}).get('generated_at')
            except (ValueError, AttributeError):
                row['generated_at'] = None
        rows[name] = row
    return rows


def build_manifest(before, after, outcomes, run):
    rows = {}
    for name, current in after.items():
        producer = PRODUCERS[name]
        outcome = outcomes.get(producer, 'unknown')
        changed = current.get('sha256') != before.get(name, {}).get('sha256')
        rows[name] = {**current, 'producer_step': producer,
                      'producer_step_outcome': outcome,
                      'content_changed_from_checkout': changed,
                      'may_be_previous_run_output': not changed or outcome != 'success'}
    return {'run': run, 'step_outcomes': outcomes, 'files': rows,
            'note': 'A retained passed audit is not evidence that this run passed. Check producer step outcomes and content hashes; failed producers may leave partial or previous outputs.'}


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / 'audit-evidence'
    out.mkdir(exist_ok=True)
    baseline = out / 'baseline.json'
    if '--baseline' in sys.argv:
        baseline.write_text(json.dumps(capture(root), indent=2) + '\n')
        return
    before = json.loads(baseline.read_text()) if baseline.exists() else {}
    outcomes = {name: os.environ.get('AUDIT_' + name.upper(), 'unknown')
                for name in ('refresh_data', 'build_candidate', 'validate_candidate', 'promote_model', 'validate_production')}
    run = {key: os.environ.get('GITHUB_' + key.upper()) for key in ('run_id', 'run_attempt', 'sha')}
    (out / 'manifest.json').write_text(json.dumps(build_manifest(before, capture(root), outcomes, run), indent=2) + '\n')


if __name__ == '__main__':
    main()
