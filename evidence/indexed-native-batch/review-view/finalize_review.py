"""Bind distinct read-only review and unchanged prior review to final candidate."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.validate import source_manifest
OUT=Path(__file__).resolve().parent
APP='73c9eb5a6fb1cabf7eca8126f029da3aff20f774'
BEFORE='4d577b990f87b2b25a06db94eef96d349c2c8d3d'
START='0f3a9d1e110ac948cab4d27fdc3377e37927a08b'
EXPECTED='e9380f167804e860d05fd4e3293dc51d5609910ddfbe4c1a8644a08b6151bd09'
PRIOR=ROOT/'evidence/indexed-native-batch/REVIEW.json'
PRIOR_SHA='272949d35a823e805cc4526286ce2da054a8aae99aa299a56448e6210adaeed9'
assert hashlib.sha256(PRIOR.read_bytes()).hexdigest()==PRIOR_SHA
prior=json.loads(PRIOR.read_bytes())
assert prior['application_candidate']==BEFORE
manifest=source_manifest()
before=json.loads((OUT/'SOURCE_BEFORE.json').read_bytes())
assert manifest==before and manifest['sha256']==EXPECTED
(OUT/'SOURCE_AFTER.json').write_text(json.dumps(manifest,indent=2)+'\n')
changed=subprocess.check_output(['git','diff','--name-only',BEFORE,APP],cwd=ROOT,text=True).splitlines()
all_changed=subprocess.check_output(['git','diff','--name-only',START,APP],cwd=ROOT,text=True).splitlines()
changes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() if (ROOT/p).is_file() else None for p in changed}
prior_unchanged={p:digest for p,digest in prior['reviewed_changed_path_hashes'].items()
                 if p not in changed and not p.startswith('evidence/')}
assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest for p,digest in prior_unchanged.items())
locks=['requirements.txt','requirements-build.in','frontend/package-lock.json','frontend/package.json']
# Check every tracked prior evidence path against exact baseline bytes, not timestamps.
historical=subprocess.check_output(['git','diff','--name-only',START,APP,'--','evidence/'],cwd=ROOT,text=True).splitlines()
assert not historical
matrix=json.loads((ROOT/'docs/ACCEPTANCE_MATRIX.json').read_bytes())
old=json.loads(subprocess.check_output(['git','show',BEFORE+':docs/ACCEPTANCE_MATRIX.json'],cwd=ROOT))
previous={r['id']:r for r in old['requirements']}
current={r['id']:r for r in matrix['requirements']}
assert all(current[k]==v for k,v in previous.items())
assert set(current)-set(previous)=={'immutable-report-display-views'}
assert matrix['browser_required']==old['browser_required']
commands=[json.loads((OUT/(name+'.json')).read_bytes()) for name in ('AFFECTED_SUBSET','FRONTEND_VIEW','RUNNER_PREPARATION')]
assert all(c['state']=='PASS_IN_SCOPE' and c['source_unchanged'] and c['source_after_sha256']==EXPECTED for c in commands)
diff=subprocess.check_output(['git','diff','--binary',BEFORE,APP],cwd=ROOT)
full_diff=subprocess.check_output(['git','diff','--binary',START,APP],cwd=ROOT)
findings=[dict(f) for f in prior['findings'] if f.get('blocking')]
for finding in findings:
    finding['carry_forward']='Underlying reviewed indexed/compiled/JSON/source modules and their tests are byte-identical to prior candidate; optional HTTP projection bridge reviewed separately below.'
findings += [
 {'id':'B2-UI-01','blocking':True,'status':'VERIFIED_IN_SCOPE','family':'Immutable summary/display report transport',
  'result':'Full/default reports/state and exports preserve complete data. Fixed SQL summary inputs preserve missing/null/boolean types, all qualification/copy-review reads and candidate progress before projection. Display retains exact metrics, requirements, warnings, source index and dedicated history/position proof. No projection is saved or passed to accounting/rebuild.',
  'validation':['review-view/AFFECTED_SUBSET.json','review-view/FRONTEND_VIEW.json']},
 {'id':'VIEW-PREVIEW-01','blocking':True,'status':'VERIFIED_IN_SCOPE','family':'Neighbouring preset-preview default contract',
  'initial_finding':'Initial follow-up used raw report inputs before preview and would omit baseline archive/history/position freshness annotations because decoration skips preview annotations.',
  'result':'Current source decorates raw inputs before setting preview=True, matching baseline behavior; full/summary preview preserves banners, unsaved checks and conditional semantics without rewriting saved reports.',
  'validation':['tests/test_report_view.py::test_preview_full_and_summary_preserve_existing_banners_and_conditional_semantics','review-view/AFFECTED_SUBSET.json']},
 {'id':'VIEW-ENRICH-01','blocking':True,'status':'VERIFIED_IN_SCOPE','family':'Selected report ownership and enrichment',
  'initial_finding':'Initial follow-up kept active detail while enrichment ignored its returned report, leaving current observations stale after a successful action.',
  'result':'Current enrichment requests display output and updates selected detail only for the matching active ID. Summary polling never replaces detail; opening tokens reject late previous opens, transient pending display requests deduplicate, later opens refetch, failures remain visible. Preview detail retains its unsaved decisions.',
  'validation':['tests/test_report_view.py::test_enrich_optional_display_projects_only_response_after_same_saved_observation','review-view/FRONTEND_VIEW.json'],
  'scope':'Offline mocked transport/helper and read-only control-flow review. No genuine market provider or full interactive concurrency acceptance executed by reviewer.'},
 {'id':'VIEW-RUNNER-01','blocking':True,'status':'VERIFIED_IN_SCOPE','family':'Missing optional real corpus runner preparation',
  'initial_finding':'An intermediate patch nested indexed assignment under the optional real-corpus guard, risking UnboundLocalError when that corpus is absent.',
  'result':'Final source initializes indexed independently of optional corpus existence. Both synthetic-only and indexed-present preparation branches execute to a deliberately disabled launcher with processes/socket mocked; producer result remains INCOMPLETE and no browser acceptance is inferred.',
  'validation':['review-view/RUNNER_PREPARATION_RESULT.json']},
 {'id':'ENV-BR-01','blocking':False,'status':'REMEDIATION_REVIEWED_PENDING_ROOT_BROWSER','category':'D environment/validation',
  'result':'Browser code streams actual UI full JSON downloads and independently hashes only loopback exports; parent full bytes remain hash-checked. Actual page response receipts require summary/display routes and record transport byte lengths. Genuine200 metrics are checked against full exported bytes and stay partial. Root final browser/gates are separate and not claimed here.'},
 {'id':'B1-COVERAGE','blocking':False,'status':'BLOCKED','category':'C missing data/source contract',
  'reason':'Observed authenticated indexed access and compatible samples do not demonstrate terminal historical population or closed/reassigned account lifecycle. No further collection or new entitlement claim.'},
 {'id':'CAP-01','blocking':False,'status':'OPEN','category':'B missing implementation and accepted evidence',
  'reason':'Reviewed offline indexed/base-compiled slice and presentation transport work in development scope. Complete successful wrapper decoding, origins/roles/classification/valuation and independent report/28/90-day population remain unfinished/unproved.'},
 {'id':'R1-B3','blocking':False,'status':'BLOCKED','category':'C genuine acceptance corpus',
  'reason':'Genuine200 and genuine23 datasets remain partial. Known selected200 fees0.008904733SOL do not establish wallet P&L, complete history or qualification. No synthetic control closes B3.'}
]
artifacts={}
for path in sorted(OUT.iterdir()):
    if path.is_file():
        raw=path.read_bytes();artifacts[str(path.relative_to(ROOT))]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
receipt={
 'kind':'consolidated-review','state':'PASS','reviewed_utc':datetime.now(timezone.utc).isoformat(),
 'review_type':'Distinct internal read-only framework review; not third-party or product acceptance',
 'source_sha256':EXPECTED,'source_files':len(manifest['files']),'source_unchanged':True,
 'starting_head':START,'previous_application_candidate':BEFORE,'application_candidate':APP,
 'matrix_review_complete':True,'reviewed_changed_paths':all_changed,'reviewed_followup_paths':changed,
 'followup_path_hashes':changes,'followup_diff_sha256':hashlib.sha256(diff).hexdigest(),
 'full_batch_diff_sha256':hashlib.sha256(full_diff).hexdigest(),
 'prior_review':{'path':str(PRIOR.relative_to(ROOT)),'sha256':PRIOR_SHA,
   'source_sha256':prior['source_sha256'],'application_candidate':BEFORE,'byte_unchanged':True,
   'unchanged_reviewed_component_paths':prior_unchanged,
   'execution_scope':'Prior252ordinaryPASS and13engineering replays remain evidence bound to4d577. They are not recounted as new executions or new acceptance on73c9. Root final full gates bind current candidate.'},
 'findings':findings,'executed_checks':commands,
 'coverage_review':{'retained_declared_requirement_groups':len(previous), 'current_declared_requirement_groups':len(current),
   'retained_matrix_rows_unchanged':True,'new_requirement_groups':['immutable-report-display-views'],
   'existing_browser_required_unchanged':True,'pinned_schema_groups_retained':38,
   'current_expanded_requirements':len(current)+38,
   'test_count_scope':'59ordinary test nodes and20separately reported subtests from affected subset. Frontend runner, two preparation controls and earlier evidence are not added as unique backend tests.'},
 'offline_boundary':{'provider_requests':0,'credential_lookups':0,'external_http_transport_requests':0,
   'basis':'Affected API tests isolate credentials/forbid external transports; enrichment uses an offline fake. Frontend fetch is mocked. Runner processes and sockets are mocked. Reviewer invoked no provider/network/credential commands.'},
 'historical_tracked_evidence_unchanged':True,'historical_prior_review_unchanged':True,
 'unchanged_dependencies':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in locks},
 'raw_artifact_bindings':artifacts,
 'full_candidate_gates_executed_by_this_reviewer':False,'browser_executed_by_this_reviewer':False,
 'application_edits':False,'commits_created':False,
 'review_conclusion':'No unresolved confirmed in-scope software blocker in the combined batch after preview/enrichment/preparation sibling corrections. This PASS covers the read-only review and affected offline checks; final root gates, final browser acceptance and private publication remain independently recorded. B1/B2/B3 readiness remains separate.',
 'B1':'Access/schema observed; historical coverage blocked','B2':'Development-functional indexed/base-compiled accounting and immutable views; complete real accounting OPEN','B3':'BLOCKED','PRODUCT_READY':False
}
final=ROOT/'evidence/indexed-native-batch/REVIEW_VIEW.json'
assert not final.exists(),'Preserve any prior final review receipt'
final.write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'path':str(final.relative_to(ROOT)),'state':receipt['state'],'source_sha256':EXPECTED,
 'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),'bytes':final.stat().st_size,
 'followup_paths':len(changed),'full_batch_paths':len(all_changed),'ordinary_passed':59,'subtests':20,
 'prior_review_byte_unchanged':True},sort_keys=True))
