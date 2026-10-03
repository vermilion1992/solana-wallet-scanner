"""R13 parser-support dependencies, source ordering and recovery controls.

All inputs are synthetic local archives. These checks prove scoped behavior,
not mainnet format validity, profitable wallets or complete accounting.
"""
from copy import deepcopy

import pytest

from tests.review_v038.review_helpers_v038 import builder, history, pb, rebuild

BAD_VERSIONS = [pytest.param(False, id='false'), pytest.param(0.0, id='float-zero'),
                pytest.param(-1, id='negative'), pytest.param(2, id='future-version'),
                pytest.param('0', id='string-zero'), pytest.param([], id='array'),
                pytest.param({}, id='object')]
BOUNDARIES = {'opening': 0, 'intervening': 1, 'closing': 2}


@pytest.mark.parametrize('boundary', BOUNDARIES)
@pytest.mark.parametrize('version', BAD_VERSIONS)
@pytest.mark.parametrize('reverse', [False, True], ids=['preferred-first', 'alternate-first'])
def test_every_relevant_archive_requires_typed_parser_support(builder, boundary, version, reverse):
    digest = builder.link_raw_alternative(BOUNDARIES[boundary], lambda raw: raw.update(version=version), reverse=reverse)
    h = history(builder)
    archive = next(row for row in h['source_consistency']['archive_contents']['receipts'] if row['hash'] == digest)
    assert 'reviewed parser/schema contract' in archive['recovery']['action']
    assert archive['recovery']['provider_requests'] == 0
    signature = builder.records[BOUNDARIES[boundary]]['signature']
    group = h['source_consistency']['transactions'][signature]
    account = group['accounts'][pb.ACCOUNT]
    check = account['checks']['transaction_format']
    assert check['state'] == 'UNKNOWN'
    assert any(fact['hash'] == digest and fact['path'] == 'version' and fact['status'] == 'invalid'
               for fact in check['facts'])
    assert any(path['hash'] == digest and 'version' in path['paths'] for path in account['source_paths'])
    for metric in ('wallet_network_fees_sol', 'native_wallet_delta_sol'):
        assert group['native'][metric]['checks']['transaction_format']['state'] == 'UNKNOWN'
        assert h['native_address_metrics']['observed'][metric]['status'] == 'unknown'
    p = builder.derive()
    assert p['counts']['known_closed'] == 0
    row = next(row for row in p['positions'] if row['account'] == pb.ACCOUNT)
    assert row['hold_hours']['value'] is None and digest in row['sources']
    assert row['stages']['source_consistency']['state'] == 'UNKNOWN'
    assert set(h['evidence_gates'].values()) == {'UNKNOWN'}


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('version', [False, 0.0, '0'], ids=['false', 'float-zero', 'string-zero'])
def test_actual_frozen_rebuild_rejects_additional_untyped_versions(builder, boundary, version, tmp_path, monkeypatch):
    digest = builder.link_raw_alternative(BOUNDARIES[boundary], lambda raw: raw.update(version=version))
    result = rebuild(builder, tmp_path, monkeypatch, digest, f'R13_extra_{boundary}_{type(version).__name__}')
    assert result['known_closed'] == 0 and result['hold']['value'] is None
    assert result['native_observed']['wallet_network_fees_sol']['status'] == 'unknown'
    assert result['boundary_checks']['provider_calls'] == result['boundary_checks']['credential_lookups'] == 0


@pytest.mark.parametrize('selected,alternative', [(0, 'legacy'), ('legacy', 0), (0, 'omitted'), ('omitted', 0)])
@pytest.mark.parametrize('api', [False, True], ids=['direct', 'frozen-api'])
def test_supported_parser_variants_share_normalized_facts(builder, selected, alternative, api, tmp_path, monkeypatch):
    for raw in builder.raws:
        if selected == 'omitted':
            raw.pop('version', None)
        else:
            raw['version'] = selected
    builder.seed()
    def change(raw):
        if alternative == 'omitted':
            raw.pop('version', None)
        else:
            raw['version'] = alternative
        raw['synthetic_annotation'] = 'Supported parser equivalence control'
    digest = builder.link_raw_alternative(0, change)
    if api:
        result = rebuild(builder, tmp_path, monkeypatch, digest, f'R13_supported_{selected}_{alternative}')
        assert result['known_closed'] == 1 and result['hold']['value'] == '6'
    else:
        p = builder.derive()
        assert p['counts']['known_closed'] == 1 and p['positions'][0]['hold_hours']['value'] == '6'
    group = history(builder)['source_consistency']['transactions'][builder.records[0]['signature']]
    assert group['accounts'][pb.ACCOUNT]['checks']['transaction_format']['state'] == 'PASS'


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('version', [0, 1], ids=['supported', 'unsupported'])
def test_restoring_archive_integrity_does_not_override_format_support(builder, boundary, version):
    digest = builder.link_raw_alternative(BOUNDARIES[boundary], lambda raw: raw.update(version=version, synthetic_note='recovery'))
    path = builder.store.path / 'evidence' / f'{digest}.json.gz'
    original = path.read_bytes()
    refs = deepcopy(builder.cp['evidence'])
    path.unlink()
    assert builder.derive()['counts']['known_closed'] == 0
    path.write_bytes(original)
    assert builder.derive()['counts']['known_closed'] == int(version == 0)
    assert builder.cp['evidence'] == refs


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('shape', ['message', 'loaded-addresses', 'execution'])
def test_supported_version_never_substitutes_for_required_native_schema(builder, boundary, shape):
    def change(raw):
        raw['version'] = 0
        if shape == 'message':
            raw['transaction']['message'] = None
        elif shape == 'loaded-addresses':
            raw['meta']['loadedAddresses'] = None
        else:
            raw['meta'].pop('err')
    digest = builder.link_raw_alternative(BOUNDARIES[boundary], change)
    p = builder.derive()
    assert p['counts']['known_closed'] == 0
    assert p['positions'][0]['hold_hours']['value'] is None and digest in p['positions'][0]['sources']
