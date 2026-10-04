"""Final exact-source offline execution journal; evidence only, no source edits."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.validate import lock_hashes, source_manifest

EXPECTED_HEAD = '7f87d3eaba4beea793835e586836d22210b91b6d'
EXPECTED_SOURCE = 'eeb6f51777dda142376b8220896ccd768fe2c08e693873fa6630e09ed063cced'
JOURNAL = ROOT / 'evidence/genuine-wallet-batch/genuine-execution-records-verified'
JOURNAL.mkdir(exist_ok=False)
def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, value): path.write_text(json.dumps(value, indent=2) + '\n')
def head(): return subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT).decode().strip()
assert head() == EXPECTED_HEAD
assert source_manifest()['sha256'] == EXPECTED_SOURCE
input_hashes = {
 'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip': 'eec702fdd821066897710d2085bf5c39380e303e8426249e22fb6379b7ccf1b4',
 'evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json': '25f752be59154d13e8d57a15b7afcc2191582a4665f4c886ef12e22d7d0284f7',
 'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json': '97c9f92202398aef69ef0e2ce78f3d81ef67814187ca233ce5c36f8363cde9ba'}
identities={name:{'sha256':sha(ROOT/name),'bytes':(ROOT/name).stat().st_size} for name in input_hashes}
assert all(identities[name]['sha256'] == digest for name,digest in input_hashes.items())
save(JOURNAL/'INPUT_IDENTITIES.json', identities)
save(JOURNAL/'RUNTIME_AND_LOCKS.json', {'python':sys.version,'platform':platform.platform(),'locks':lock_hashes(),'candidate_application_commit':EXPECTED_HEAD})
commands = []
base=[str(ROOT/'.venv/bin/python'),'tools/check_genuine_collection.py',
      '--input','evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip',
      '--input-freeze','evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json',
      '--worked-expectations','evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json']
work = [
 ('WORKFLOW', 'genuine-workflow-verified', base, 0, 'WORKFLOW_PASS_REAL_ACCEPTANCE_BLOCKED', 'genuine'),
 ('REAL_REQUIRED','genuine-real-required-verified',base+['--require-real-acceptance'],2,'BLOCKED','genuine'),
 ('PRODUCT_DEVELOPMENT','product-development-verified',[str(ROOT/'.venv/bin/python'),'tools/check_product.py'],0,'DEVELOPMENT_PASS','development'),
 ('PRODUCT_REAL_REQUIRED','product-real-required-verified',[str(ROOT/'.venv/bin/python'),'tools/check_product.py','--require-real-acceptance'],2,'BLOCKED','development')]
for kind, output_name, args, expected_exit, expected_state, scope in work:
    output='evidence/genuine-wallet-batch/'+output_name
    assert not (ROOT/output).exists()
    argv=args+['--output',output]
    before=source_manifest()
    assert before['sha256']==EXPECTED_SOURCE and len(before['files'])==227
    before_head=head()
    save(JOURNAL/(kind+'_SOURCE_BEFORE.json'), before)
    command={'kind':kind,'argv':argv,'cwd':str(ROOT),'start':now(),'scope':scope,
             'source_before_sha256':before['sha256'],'head_before':before_head,'input_identities':identities,
             'expected_exit_code':expected_exit,'expected_state':expected_state}
    save(JOURNAL/(kind+'_RUNNING.json'),command)
    print(json.dumps({'begin':kind,'start':command['start'],'argv':argv}),flush=True)
    log=JOURNAL/(kind.lower()+'.log')
    with log.open('wb') as target:
        process=subprocess.run(argv,cwd=ROOT,stdout=target,stderr=subprocess.STDOUT)
    after=source_manifest()
    after_head=head()
    save(JOURNAL/(kind+'_SOURCE_AFTER.json'), after)
    command.update(end=now(),exit_code=process.returncode,source_after_sha256=after['sha256'],
                   source_unchanged=before==after,head_after=after_head,
                   log=str(log.relative_to(JOURNAL)),log_sha256=sha(log),log_bytes=log.stat().st_size)
    save(JOURNAL/(kind+'_COMMAND.json'), command)
    result_path=ROOT/output/'result.json'
    result=json.loads(result_path.read_bytes())
    summary={'state':result['state'],'command_exit':process.returncode,
             'cases':[{key:case[key] for key in ('case','state','report_role','side') if key in case} for case in result['cases']],
             'scoped_case_entries':len(result['cases']),
             'provider_requests':result['provider_requests'],'credential_lookups':result['credential_lookups'],
             'parent_unchanged':result.get('parent_unchanged'),
             'result':str(result_path.relative_to(ROOT)),'result_sha256':sha(result_path),
             'real_acceptance':result['real_acceptance'],'source_unchanged':before==after,
             'candidate_application_commit':EXPECTED_HEAD,'application_source_sha256':EXPECTED_SOURCE,
             'count_scope':'Replay scenarios overlap earlier executions and each other; not additional unique tests.'}
    if scope == 'genuine':
        summary['usage_unchanged']=result['usage_unchanged']
        summary['normal_report_builds']=8
        summary['PRODUCT_READY']=result['PRODUCT_READY']
        summary['query_intervals']={key:{'state':value['state'],'query_records_state':value['query_records_state'],
                                      'supported_record_state':value['supported_record_state'],
                                      'record_count':value['record_count'],'gaps':value['gaps']}
                                    for key,value in result['query_coverage']['intervals'].items()}
        summary['historical_population_state']=result['query_coverage']['historical_population']['state']
        summary['format_population_state']=result['query_coverage']['provider_contract']['format_population_state']
        parent=json.loads((ROOT/output/'parent-report.json').read_bytes())
        summary['observed_network_fees_sol']=parent['metrics']['observed_network_fees_sol']
        summary['supported_selected_lots']=parent['coverage']['wallet_evidence']['query_accounting']['supported_selected_lots']
        assert len(result['cases'])==7 and all(case['state']=='PASS' for case in result['cases'])
        assert all(interval['state']=='PASS' and interval['record_count']==87 and interval['gaps']==[]
                   for interval in summary['query_intervals'].values())
        assert summary['historical_population_state']=='UNKNOWN' and summary['format_population_state']=='UNKNOWN'
        assert summary['observed_network_fees_sol']['status']=='known' and summary['observed_network_fees_sol']['value']=='0.000158868'
        lot=next(lot for lot in summary['supported_selected_lots'] if lot['mint']=='BQJfL1yiHbJQ8AciHLcKxaCbQrWP2ws8oZHHYgbBpump')
        assert lot['monetary_state']=='PASS' and lot['timing_state']=='PASS' and lot['quantity_state']=='PASS'
        assert lot['conditional_lot_profit_sol']=='-0.013270924' and lot['conditional_basis_sol']=='0.565194018'
        assert result['usage_unchanged'] is True and result['PRODUCT_READY'] is False
    else:
        summary['development']=result['development']
        assert result['development']['state']=='PASS'
        assert len(result['cases'])==4 and all(case['state']=='PASS' for case in result['cases'])
    save(JOURNAL/(kind+'_SUMMARY.json'), summary)
    assert before==after and after['sha256']==EXPECTED_SOURCE
    assert process.returncode==expected_exit and result['state']==expected_state
    assert result['provider_requests']==0 and result['credential_lookups']==0
    assert result['parent_unchanged'] is True and result['real_acceptance']['state']=='BLOCKED'
    commands.append(command)
    save(JOURNAL/'EXECUTIONS.json',commands)
    print(json.dumps({'end':kind,'exit':process.returncode,'state':result['state'],'cases':len(result['cases']),
                      'source_unchanged':before==after,'provider_requests':result['provider_requests'],
                      'credential_lookups':result['credential_lookups']}),flush=True)
save(JOURNAL/'FINAL_STATUS.json', {'candidate_application_commit':EXPECTED_HEAD,'source_sha256':EXPECTED_SOURCE,
     'source_files':227,'completed_executions':4,'genuine_scoped_scenarios':7,'genuine_report_builds_per_execution':8,
     'development_cases':4,'count_scope':'No sum of overlapping replays; scenarios/captures are not unique test nodes.',
     'offline_guards_zero':True,'parent_immutability':True,'real_acceptance':'BLOCKED','PRODUCT_READY':False})
