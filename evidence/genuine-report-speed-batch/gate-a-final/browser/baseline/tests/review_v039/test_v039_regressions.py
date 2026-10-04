"""R14: account-list precedence must not hide parsed ownership operations.

Ordinary failing assertions on v0.3.9. All evidence is synthetic and local.
The assertions demand uncertainty, never certification or trading behavior.
"""
import pytest
from tests.review_v039.review_helpers import (builder, history, summarize, record_result, rebuild,
                            add_ownership_source, SOURCE_MODES, LOCATIONS, MASKS, pb)

@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('mask', MASKS)
def test_contradictory_instruction_references_revoke_hold(builder, mode, location, mask):
    digest = add_ownership_source(builder, mode, location, mask)
    p = builder.derive()
    h = history(builder)
    result = summarize(p, h, digest)
    result['case'] = {'mode': mode, 'location': location, 'mask': mask, 'digest': digest}
    record_result(f'R14_{mode}_{location}_{mask}_direct.json', result)
    assert set(h['evidence_gates'].values()) == {'UNKNOWN'}
    assert digest in result['sources']
    assert result['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'
    assert p['counts']['known_closed'] == 0, result
    assert result['hold']['status'] == 'unknown' and result['hold']['value'] is None

@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
def test_contradictory_instruction_references_revoke_actual_rebuild(builder, mode, location, tmp_path, monkeypatch):
    digest = add_ownership_source(builder, mode, location, 'empty')
    label = f'R14_{mode}_{location}_api'
    result = rebuild(builder, tmp_path, monkeypatch, digest, label)
    result['case'] = {'mode': mode, 'location': location, 'mask': 'empty', 'digest': digest}
    record_result(label+'.json', result)
    assert result['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'
    assert result['known_closed'] == 0, result
    assert result['hold']['status'] == 'unknown' and result['hold']['value'] is None
