"""R12: an unreadable linked signature-page must not disappear from dependencies.

These are ordinary assertions, not expected failures. The release is not patched.
"""
import pytest
from tests.review_v037.review_helpers import (builder, conflict_page, evidence_file, damage, history, summary,
                            write_result, api_damage_sequence)

@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('variant', ['missing', 'corrupt'])
def test_lost_linked_page_cannot_upgrade_a_conflicted_hold(builder, boundary, variant):
    ref = conflict_page(builder, boundary)
    digest = ref['hash']; archive = evidence_file(builder, digest); original = archive.read_bytes()
    before = summary(builder.derive(), history(builder), digest)
    assert before['known_closed'] == 0
    damage(archive, variant)
    damaged = summary(builder.derive(), history(builder), digest)
    archive.write_bytes(original)
    restored = summary(builder.derive(), history(builder), digest)
    assert restored['known_closed'] == 0
    assert ref in builder.cp['evidence']
    write_result(f'R12_{boundary}_{variant}_direct.json', {'reference': ref, 'before': before,
                  'damaged': damaged, 'restored': restored, 'reference_count': len(builder.cp['evidence'])})
    assert damaged['known_closed'] == 0, damaged
    assert damaged['hold']['value'] is None
    assert damaged['native_observed']['native_wallet_delta_sol']['status'] == 'unknown'
    assert damaged['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'

@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('variant', ['missing', 'corrupt'])
def test_lost_linked_page_cannot_upgrade_actual_frozen_rebuild(builder, boundary, variant, tmp_path, monkeypatch):
    ref = conflict_page(builder, boundary)
    sequence, boundaries = api_damage_sequence(builder, tmp_path, monkeypatch, ref['hash'], variant)
    assert sequence[0]['known_closed'] == sequence[2]['known_closed'] == 0
    write_result(f'R12_{boundary}_{variant}_api.json', {'reference': ref, 'sequence': sequence, 'boundary_checks': boundaries})
    assert sequence[1]['known_closed'] == 0, sequence[1]
    assert sequence[1]['hold']['value'] is None
    assert sequence[1]['native_observed']['native_wallet_delta_sol']['status'] == 'unknown'
    assert sequence[1]['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'
