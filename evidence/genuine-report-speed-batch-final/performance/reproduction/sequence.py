"""Corrected-freeze normal timings only; never application acceptance."""
from pathlib import Path
import argparse, datetime, hashlib, json, sqlite3, subprocess, sys, time
ROOT = Path('/workspace/solana-wallet-scanner')
sys.path.insert(0, str(ROOT))
from tools.validate import source_manifest

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--source-files', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    expected = {'commit': args.commit, 'source_sha256': args.source_sha256, 'source_files': args.source_files}
    output = args.output.resolve()
    assert ROOT not in output.parents and output != ROOT
    assert not output.exists()
    def source():
        manifest = source_manifest(ROOT)
        return {'commit': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
            'source_sha256': manifest['sha256'], 'source_files': len(manifest['files'])}
    assert source() == expected
    originals = [ROOT / name for name in (
        'evidence/source-probe-2026-10-04/live/02-all-index-request.json',
        'evidence/source-probe-2026-10-04/live/02-all-index-response.raw.gz',
        'evidence/source-probe-2026-10-04/live/03-all-continuation-request.json',
        'evidence/source-probe-2026-10-04/live/03-all-continuation-response.raw.gz',
        'requirements.txt','requirements-build.in','pyproject.toml','frontend/package-lock.json')]
    archive200 = Path('/workspace/outputs/report-proof-profile/baseline-ab62858/input.zip')
    archive87 = Path('/workspace/outputs/genuine-wallet-inventory/genuine87-inventory-input.zip')
    oracle200 = Path('/workspace/outputs/report-proof-profile/baseline-ab62858/EXPECTED_RAW.json')
    oracle87 = ROOT / 'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json'
    tracked_inputs = originals + [archive200, archive87, oracle200, oracle87]
    def inputs():
        return {str(path): {'bytes':path.stat().st_size,'sha256':sha(path.read_bytes())} for path in tracked_inputs}
    before = inputs()
    assert before[str(archive200)]['sha256'] == '823a535edbcc4a84c5d293c6bafad2a504f0929bf76fe085d05937133c47d9f0'
    assert before[str(archive87)]['sha256'] == 'ac154d0f32192e1f6122c0703054a1570c661c311a7c1ca7705442183cdada33'
    worked200, worked87 = json.loads(oracle200.read_text()), json.loads(oracle87.read_text())
    expected_fee200 = worked200['observed_network_fees_sol']['value']
    expected_fee87 = worked87['network_fee_totals']['independent_intervals']['report']['network_fee_sol']
    assert expected_fee200 == '0.008904733' and expected_fee87 == '0.000158868'
    output.mkdir(parents=True, exist_ok=False)
    index = {'kind':'corrected-freeze-normal-performance-sequence','acceptance_run':False,
        'product_readiness_claim':False,'profile_enabled':False,'source_before':source(),
        'input_lock_hashes_before':before,'commands':[],
        'scope':'Normal offline archive observations only. Old full-candidate failure is retained; these observations do not establish full Gate A or product readiness.'}
    def save():
        (output / 'INDEX.json').write_text(json.dumps(index,indent=2)+'\n')
    save()
    python = ROOT / '.venv/bin/python'
    cli = ROOT / 'tools/benchmark_report.py'
    for name, archive, expected_fee in [('genuine200-normal',archive200,expected_fee200),('genuine87-augmented-normal',archive87,expected_fee87)]:
        assert source() == expected and inputs() == before
        run = output / name
        command = [str(python),str(cli),'--archive',str(archive),'--output',str(run),'--full-details']
        log = output / (name+'-outer.log')
        print('START '+name, flush=True)
        clock = time.perf_counter()
        with log.open('wb') as stream:
            try:
                process = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
                exit_code, timed_out = process.returncode, False
            except subprocess.TimeoutExpired:
                exit_code, timed_out = None, True
        raw = log.read_bytes()
        row = {'name':name,'command':command,'seconds':time.perf_counter()-clock,'exit_code':exit_code,
            'outer_timed_out':timed_out,'timeout_seconds':300,'log':str(log),'log_bytes':len(raw),'log_sha256':sha(raw)}
        index['commands'].append(row)
        row['source_after'] = source()
        save()
        assert exit_code == 0 and not timed_out, (name,row,raw.decode(errors='replace')[-3000:])
        receipt_path = run / 'observations.json'
        receipt = json.loads(receipt_path.read_text())
        row.update({'receipt':str(receipt_path),'receipt_sha256':sha(receipt_path.read_bytes()),'state':receipt['state']})
        assert receipt['state'] == 'OBSERVED' and not receipt['acceptance_run'] and not receipt['product_readiness_claim']
        assert not receipt['profile_enabled'] and receipt['full_details_enabled'] and receipt['full_export_equivalence']
        assert all(value == 0 for value in receipt['calls'].values())
        assert receipt['invariants'] and all(value is True for value in receipt['invariants'].values())
        assert receipt['parent']['fee_observation']['value'] == expected_fee
        assert receipt['parent']['qualification']['profit_sol'] is None and receipt['parent']['qualification']['qualified'] is False
        parent = receipt['parent']['report_id']
        db = run / 'private-runtime/scanner.sqlite'
        with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as connection:
            def field(path):
                value = connection.execute('SELECT json_extract(payload,?) FROM records WHERE kind=? AND id=?',
                    (path,'reports',parent)).fetchone()[0]
                return json.loads(value) if isinstance(value,str) and value.startswith(('{','[')) else value
            metrics = field('$.metrics')
            assert metrics['profit_sol']['status'] == 'unknown' and metrics['profit_sol']['value'] is None
            scoped = {'kind':'genuine-normal-scoped-oracle-recheck','acceptance_run':False,'source':expected,
                'archive_sha256':before[str(archive)]['sha256'],'observed_network_fees_sol':expected_fee,
                'whole_wallet_profit_status':metrics['profit_sol']['status'],'qualified':False,
                'invariants':receipt['invariants'],'calls':receipt['calls']}
            if name == 'genuine87-augmented-normal':
                lots = field('$.archive_accounting.query_accounting.supported_selected_lots')
                worked_lot = worked87['supported_selected_lots'][0]
                supported = [lot for lot in lots if lot.get('conditional_lot_profit_sol') is not None]
                assert len(supported) == 1
                lot = supported[0]
                assert lot['mint'] == worked_lot['mint'] and lot['conditional_lot_profit_sol'] == worked_lot['conditional_lot_profit_sol']
                assert lot['monetary_state'] == 'PASS' and lot['timing_state'] == 'PASS' and lot['wallet_population_state'] == 'UNKNOWN'
                bounds = lot['fifo_bounds']
                holding = (datetime.datetime.fromisoformat(bounds['end'])-datetime.datetime.fromisoformat(bounds['start'])).total_seconds()
                assert holding == worked_lot['hold_seconds'] == 529
                inventory = field('$.coverage.wallet_evidence.inventory_observations')
                native = inventory['components']['native_lamports']
                assert native['state'] == 'PASS' and [x['lamports'] for x in native['observations']] == ['650240']
                assert inventory['historical_population_state'] == 'UNKNOWN'
                assert inventory['valuation_state'] == 'UNKNOWN'
                scoped.update({'existing_worked_oracle':str(oracle87),'oracle_sha256':before[str(oracle87)]['sha256'],
                    'supported_lots':supported,'holding_seconds':holding,'inventory_native_lamports':'650240',
                    'inventory_historical_population':'UNKNOWN','inventory_valuation':'UNKNOWN'})
            else:
                scoped.update({'existing_worked_oracle':str(oracle200),'oracle_sha256':before[str(oracle200)]['sha256'],
                    'selected_record_count':worked200['unique_signatures'],'population_scope':'Partial nonterminal provider pages; no complete wallet qualification.'})
        oracle_path = output / (name+'-SCOPED_ORACLE_RECHECK.json')
        oracle_path.write_text(json.dumps(scoped,indent=2)+'\n')
        row['oracle_recheck'] = {'path':str(oracle_path),'sha256':sha(oracle_path.read_bytes())}
        assert source() == expected and inputs() == before
        save()
        print('END '+name+' '+str(exit_code)+' '+str(round(row['seconds'],3)),flush=True)
    index.update({'source_after':source(),'input_lock_hashes_after':inputs(),'state':'OBSERVED_BOTH_NORMAL_OFFLINE_OPERATIONS'})
    assert index['source_after'] == expected and index['input_lock_hashes_after'] == before
    save()
    print('FINAL '+index['state'],flush=True)

if __name__ == '__main__':
    main()
