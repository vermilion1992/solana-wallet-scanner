"""R13: an unsupported/malformed linked transaction version cannot certify a hold.

These assertions use the release's own source-version predicate. They do not
assert that version 1 is invalid on Solana, only unsupported by this release.
"""
import pytest
from tests.review_v038.review_helpers_v038 import builder, add_version_source, history, summarize, record_result, rebuild
VERSIONS=[pytest.param(1,id='unsupported-v1'),pytest.param(True,id='boolean-version'),pytest.param(None,id='null-version')]

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('version',VERSIONS)
def test_unsupported_linked_version_revokes_account_hold(builder,boundary,version):
    digest=add_version_source(builder,boundary,version)
    result=summarize(builder.derive(),history(builder),digest)
    # Earlier versions lack typed archive receipts; the outcome assertion is identical.
    if result['archive_receipt'] is not None:
        assert result['archive_receipt']['state']=='UNKNOWN'
        assert result['archive_receipt']['read_state']=='readable'
    assert result['version_source_cited'] is True
    assert set(result['evidence_gates'].values())=={'UNKNOWN'}
    record_result(f'R13_{boundary}_{str(version).lower()}_direct.json',result)
    assert result['known_closed']==0,result
    assert result['hold']['value'] is None
    assert result['stages']['source_consistency']['state']=='UNKNOWN'

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('version',VERSIONS)
def test_unsupported_linked_version_revokes_actual_rebuild(builder,boundary,version,tmp_path,monkeypatch):
    digest=add_version_source(builder,boundary,version)
    label=f'R13_{boundary}_{str(version).lower()}_api'
    result=rebuild(builder,tmp_path,monkeypatch,digest,label)
    assert result['archive_receipt']['state']=='UNKNOWN'
    record_result(label+'.json',result)
    assert result['known_closed']==0,result
    assert result['hold']['value'] is None
    assert result['stages']['source_consistency']['state']=='UNKNOWN'
