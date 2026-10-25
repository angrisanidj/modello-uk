"""Publication policy tests using the frozen, valid production candidate."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('promotion', ROOT/'tools/promote_mrp_stack.py')
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


class PromotionSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def load(name):
            return json.loads((ROOT/'data'/name).read_text())
        cls.source = load('mrp-lite-live-v0928-candidate.json')
        cls.backtest = load('backtest-v0928-geography-stack.json')
        cls.integrity = load('bes-integrity-v0928.json')

    def setUp(self):
        self.candidate = copy.deepcopy(self.source)
        self.history = copy.deepcopy(self.backtest)

    def validate(self):
        return promotion.validate_candidate(self.candidate, self.history, self.integrity)

    def test_76_disagreements_publish_with_explicit_sensitivity_warning(self):
        self.candidate['live_2026_sensitivity']['changed_winners_vs_primary']['direct_mic26'] = 76
        audit = self.validate()
        self.assertEqual(audit['status'], 'passed', audit['errors'])
        self.assertFalse(audit['gates']['core_2026_stability_passed'])
        self.assertTrue(audit['gates']['core_2026_sensitivity_diagnostics_valid'])
        self.assertFalse(audit['gates']['core_2026_stability_blocking'])
        self.assertTrue(any('75' in w and '76' in w for w in audit['warnings']))
        original = copy.deepcopy(self.candidate)
        production = promotion.build_production(self.candidate, self.history, audit)
        self.assertEqual(production['seats'], original['seats'])
        self.assertEqual(production['target_gb'], original['target_gb'])
        self.assertEqual(self.candidate, original)

    def test_75_disagreements_remain_within_warning_threshold(self):
        self.candidate['live_2026_sensitivity']['changed_winners_vs_primary']['direct_mic26'] = 75
        audit = self.validate()
        self.assertEqual(audit['status'], 'passed')
        self.assertTrue(audit['gates']['core_2026_stability_passed'])

    def test_missing_diagnostic_still_blocks(self):
        del self.candidate['live_2026_sensitivity']['changed_winners_vs_primary']['direct_mic26']
        self.assertEqual(self.validate()['status'], 'failed')

    def test_invalid_counts_still_block(self):
        for value in [-1, 633, 76.5, '76', True, None]:
            with self.subTest(value=value):
                self.candidate['live_2026_sensitivity']['changed_winners_vs_primary']['direct_mic26'] = value
                audit = self.validate()
                self.assertEqual(audit['status'], 'failed')
                self.assertFalse(audit['gates']['core_2026_sensitivity_diagnostics_valid'])

    def test_malformed_diagnostic_container_returns_failed_audit(self):
        for value in [None, [], "bad"]:
            with self.subTest(value=value):
                self.candidate['live_2026_sensitivity'] = value
                self.assertEqual(self.validate()['status'], 'failed')

    def test_historical_regression_still_blocks(self):
        self.history['strength_selection_2019']['selected']['correct_winners'] = 608
        self.assertEqual(self.validate()['status'], 'failed')

    def test_bad_shares_still_block(self):
        self.candidate['seats'][0]['projected']['lab'] = float('nan')
        self.assertEqual(self.validate()['status'], 'failed')

    def test_incomplete_source_still_blocks(self):
        self.candidate['source_meta']['mic2026']['mapped_columns'].pop('green')
        self.assertEqual(self.validate()['status'], 'failed')


import sys
import tempfile
sys.path.insert(0, str(ROOT / "tools"))
from write_run_audit_manifest import capture, build_manifest

class RunAuditManifestTests(unittest.TestCase):
    def test_old_passed_audit_is_marked_as_previous_when_promotion_skipped(self):
        before={'data/promotion-audit-v0929.json':{'exists':True,'sha256':'same','generated_at':'old'}}
        report=build_manifest(before,before,{'promote_model':'skipped'}, {'run_id':'123'})
        row=report['files']['data/promotion-audit-v0929.json']
        self.assertFalse(row['content_changed_from_checkout'])
        self.assertTrue(row['may_be_previous_run_output'])
        self.assertEqual(row['producer_step_outcome'],'skipped')
        self.assertEqual(report['run']['run_id'],'123')

    def test_failed_producer_does_not_claim_changed_output_is_valid(self):
        before={'data/mrp-geography-stack-v0928.json':{'exists':True,'sha256':'old'}}
        after={'data/mrp-geography-stack-v0928.json':{'exists':True,'sha256':'new'}}
        row=build_manifest(before,after,{'build_candidate':'failure'}, {})['files']['data/mrp-geography-stack-v0928.json']
        self.assertTrue(row['content_changed_from_checkout'])
        self.assertTrue(row['may_be_previous_run_output'])
        self.assertEqual(row['producer_step_outcome'],'failure')

    def test_capture_records_missing_and_present_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'data').mkdir()
            (root/'data/polls.json').write_text('{"meta":{"generated_at":"now"},"polls":[]}')
            rows=capture(root)
            self.assertEqual(rows['data/polls.json']['generated_at'],'now')
            self.assertEqual(len(rows['data/polls.json']['sha256']),64)
            self.assertFalse(rows['data/promotion-audit-v0929.json']['exists'])

if __name__ == '__main__':
    unittest.main()
