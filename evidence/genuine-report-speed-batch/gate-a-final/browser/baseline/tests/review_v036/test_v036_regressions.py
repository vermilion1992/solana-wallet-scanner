"""R11: an inspection limit must not certify an incompletely checked source set.
Ordinary failing assertions against unmodified v0.3.6. All inputs are synthetic.
"""
import pytest
from tests.review_v036.review_helpers import builder, capped_alternative, record, rebuild_api

@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_conflicting_reference_after_actual_limit_must_revoke_hold(builder, boundary):
    reference = capped_alternative(builder, boundary)
    result = builder.derive()
    record(f'R11_{boundary}_direct.json', {'reference_count': len(builder.cp['evidence']),
        'omitted_reference': reference, 'result': result})
    assert result['counts']['known_closed'] == 0, result['counts']
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'
    assert result['positions'][0]['hold_hours']['value'] is None

@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_conflicting_reference_after_actual_limit_must_not_survive_rebuild_api(builder, boundary, tmp_path, monkeypatch):
    reference = capped_alternative(builder, boundary)
    child, limits = rebuild_api(builder, tmp_path, monkeypatch)
    result = child['coverage']['position_evidence']
    record(f'R11_{boundary}_api.json', {'boundary_checks': limits, 'omitted_reference': reference,
        'position_result': result, 'history': child['coverage']['history_evidence']})
    assert result['counts']['known_closed'] == 0, result['counts']
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'
    assert result['positions'][0]['hold_hours']['value'] is None
