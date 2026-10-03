"""Acceptance records must bind their gates; backend green alone is insufficient."""
import json
from pathlib import Path
import pytest
from tools.validate import gate_decision,required_record

@pytest.mark.parametrize('state,expected',[('FAILED',1),('BLOCKED',2),('INCOMPLETE',2)])
def test_one_unclosed_required_gate_prevents_acceptance(state,expected):
    result,code=gate_decision([{'state':'PASS'},{'state':state}],stable=True)
    assert code==expected and result!='ACCEPTED_IN_SCOPE'

def test_changed_candidate_cannot_use_old_results():
    assert gate_decision([{'state':'PASS'}],stable=False)==('INCOMPLETE',2)

def test_missing_review_prevents_acceptance(tmp_path):
    assert required_record(tmp_path/'missing.json',kind='consolidated-review',locks={},source_hash='a')['state']=='INCOMPLETE'

def test_stale_review_and_live_blocker_are_not_accepted(tmp_path):
    p=tmp_path/'review.json';r={'kind':'consolidated-review','state':'PASS','source_sha256':'old','matrix_review_complete':True,'findings':[]};p.write_text(json.dumps(r))
    assert required_record(p,kind='consolidated-review',locks={},source_hash='new')['state']=='INCOMPLETE'
    r.update(source_sha256='new',findings=[{'blocking':True,'status':'OPEN'}]);p.write_text(json.dumps(r))
    assert required_record(p,kind='consolidated-review',locks={},source_hash='new')['state']=='FAILED'
    r['findings'][0]['status']='VERIFIED_IN_SCOPE';p.write_text(json.dumps(r))
    assert required_record(p,kind='consolidated-review',locks={},source_hash='new')['state']=='PASS'

@pytest.mark.parametrize('change',['locks','command'])
def test_install_record_needs_current_locks_and_successful_command(tmp_path,change):
    p=tmp_path/'install.json';r={'kind':'clean-locked-install','state':'PASS','disposable_install':True,'locks':{'r':'a'},'commands':[{'exit_code':0}]}
    if change=='locks':r['locks']={'r':'b'}
    else:r['commands'][0]['exit_code']=1
    p.write_text(json.dumps(r));assert required_record(p,kind='clean-locked-install',locks={'r':'a'})['state']!='PASS'

def test_install_cache_is_bound_to_the_runtime_as_well_as_locks(tmp_path):
    p=tmp_path/'install.json';p.write_text(json.dumps({'kind':'clean-locked-install','state':'PASS','disposable_install':True,'locks':{'r':'a'},'commands':[{'exit_code':0}],'runtime':{'python':'old'}}))
    assert required_record(p,kind='clean-locked-install',locks={'r':'a'},runtime={'python':'new'})['state']=='INCOMPLETE'
