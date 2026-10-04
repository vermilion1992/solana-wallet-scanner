"""Read-only cash-role consumer replay, separate from genuine acceptance."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from tools.validate import source_manifest
from scanner.investigation import decode_supported_swaps
from scanner.research import summarize_research
from scanner.wallet_evidence import derive_wallet_evidence
from scanner.copy_review import qualify_report, review_copy_behavior
from test_retained_protocol_funding import native_pair, wrapped, cash, WINDOW
from test_copy_review import report as strict_model, observed_report, episode as episode_model


def main(args):
    before = source_manifest()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    assert commit == args.commit and before['sha256'] == args.source_sha256
    raw, wallet, foreign = native_pair()
    rows, clean = [], None
    for name, ordinal in [('positive-clean', None), ('buy-net-zero-foreign-loop', 0), ('sell-net-zero-foreign-loop', 1)]:
        current = deepcopy(raw)
        if ordinal is not None:
            current[ordinal]['meta']['innerInstructions'][0]['instructions'] += [cash(wallet, foreign, 1), cash(foreign, wallet, 1)]
        original = deepcopy(current)
        records = [wrapped(item) for item in current]
        events = decode_supported_swaps(records, wallet)['events']
        receipt = derive_wallet_evidence(records, all_records=records, wallet=wallet,
                                        window=WINDOW, source_consistency={}, chronology={})
        result = summarize_research(events, WINDOW['start'], WINDOW['end'], wallet_evidence=receipt)
        if ordinal is None:
            clean = result
            assert result['conditional_observed_lot_profit_sol'] == '-0.10001'
            assert result['episodes'][0]['monetary_state'] == 'PASS'
        else:
            assert result['unresolved_transactions'] == 2
            assert result['conditional_observed_lot_profit_sol'] is None
            assert result['sales_detail'][0]['conditional_profit_sol'] is None
            episode = result['episodes'][0]
            assert episode['pnl_sol'] is episode['roi_pct'] is None
            assert episode['monetary_state'] == 'UNKNOWN'
            assert episode['quantity_state'] == episode['timing_state'] == 'PASS'
            for key in ('hold_hours', 'first_sale_hours', 'acquired_raw', 'sold_raw'):
                assert episode[key] == clean['episodes'][0][key]
            if ordinal == 0:
                assert result['sales_detail'][0]['conditional_matched_basis_sol'] is None
            else:
                assert result['sales_detail'][0]['conditional_matched_basis_sol'] == '1.000005'
            assert summarize_research(list(reversed(events)), WINDOW['start'], WINDOW['end'], wallet_evidence=receipt) == result
        assert current == original
        assert result['wallet_fees_paid_sol'] == '0.00001'
        rows.append({'case': name, 'state': 'PASS',
                     'cash_role_states': [event.get('native_cash_role_state') for event in events if event['kind'] in ('buy', 'sell')],
                     'unresolved_transactions': result['unresolved_transactions'],
                     'conditional_profit_sol': result['conditional_observed_lot_profit_sol'],
                     'sales_detail': result['sales_detail'],
                     'episode_money': {key: result['episodes'][0][key] for key in ('basis_sol', 'matched_basis_sol', 'proceeds_sol', 'pnl_sol', 'roi_pct', 'monetary_state', 'quantity_state', 'timing_state')},
                     'wallet_fees_paid_sol': result['wallet_fees_paid_sol'], 'raw_input_unchanged': True})
    strict = strict_model()
    strict['research']['version'] = 'supported-subset-research-v2'
    strict['positions'] = [episode_model(hold='2', exit90='0.05', first='0.01')]
    strict_original = deepcopy(strict)
    qualified = qualify_report(strict)
    strict_review = review_copy_behavior(strict)
    assert qualified['qualified'] is True
    assert strict_review['conditional'] is False
    assert strict_review['checks']['long_tail_holds']['state'] == 'OBSERVED'
    assert strict == strict_original
    fallback = observed_report()
    fallback['research']['version'] = 'supported-subset-research-v2'
    fallback_original = deepcopy(fallback)
    stale_review = review_copy_behavior(fallback)
    assert stale_review['conditional'] is True
    assert stale_review['checks']['research_methodology']['state'] == 'UNKNOWN'
    assert stale_review['checks']['long_tail_holds']['state'] == 'UNKNOWN'
    assert stale_review['checks']['rapid_first_sales']['state'] == 'UNKNOWN'
    assert stale_review['checks']['unmatched_basis']['state'] == 'UNKNOWN'
    assert fallback == fallback_original
    isolation = {'case': 'current-strict-and-stale-fallback-research-generation-isolation',
                 'state': 'PASS', 'strict_current_qualification_preserved': qualified['qualified'],
                 'strict_current_positions_used': strict_review['conditional'] is False,
                 'stale_fallback_timing_unknown': True, 'inputs_unchanged': True,
                 'scope': 'Development saved-report predicate controls; not fabricated genuine qualification or B3.'}
    after = source_manifest()
    assert before == after
    report = {'kind': 'distinct-read-only-current-cash-role-consumer-replay', 'state': 'PASS',
              'application_commit': commit, 'source_sha256': before['sha256'], 'source_files': len(before['files']),
              'source_unchanged_before_after': True, 'rows': rows,
              'generation_isolation': isolation,
              'scope': 'Three unsigned development diagnostics; not a genuine independent oracle, complete wallet, full acceptance or unique backend nodes. No provider/credential calls.',
              'source_subset_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                      for name in ('scanner/research.py', 'scanner/investigation.py', 'scanner/wallet_evidence.py')}}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'state': report['state'], 'application_commit': commit, 'source_sha256': before['sha256'], 'diagnostics': len(rows)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
