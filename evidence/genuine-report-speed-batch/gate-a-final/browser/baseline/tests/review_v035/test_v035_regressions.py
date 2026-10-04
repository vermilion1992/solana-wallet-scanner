"""R10: contradictory token-balance receipts must invalidate the dependent hold.
Synthetic source-validation controls only; no signed/mainnet claims or provider IO.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest
from tests import test_position_evidence as pb
from tests.review_v033.review_helpers import position_builder, assert_unknown_hold
from tests.review_v033.test_v033_regressions import _rebuild_via_api


def alternate_balance(builder, boundary, reverse=False):
    index = 0 if boundary == 'opening' else 2
    original = deepcopy(builder.raws[index])
    alternative = deepcopy(original)
    # Keep transferred units, mint, owner, slot, time, fee and signature identical.
    # Opening: preferred 0 -> 100; alternative 200 -> 300.
    # Closing: preferred 50 -> 0; alternative 51 -> 1.
    offset = 200 if boundary == 'opening' else 1
    for field in ('preTokenBalances', 'postTokenBalances'):
        balance = next(row for row in alternative['meta'][field] if row['accountIndex'] == 1)
        balance['uiTokenAmount']['amount'] = str(int(balance['uiTokenAmount']['amount']) + offset)
    signature = original['transaction']['signatures'][0]
    digest = builder.store.archive(alternative)
    assert digest != builder.records[index]['evidence_hash']
    builder.cp['evidence'].append({'hash': digest, 'kind': 'transaction', 'signature': signature})
    if reverse:
        builder.cp['evidence'].reverse()
    builder.persist()
    return {'signature': signature, 'preferred_hash': builder.records[index]['evidence_hash'],
            'alternative_hash': digest, 'original': original, 'alternative': alternative}


def record_output(name, payload):
    output = os.environ.get('REVIEW_OUTPUT')
    if output:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(json.dumps(payload, indent=2))


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('reverse', [False, True])
def test_conflicting_token_boundaries_cannot_certify_account_hold(position_builder, boundary, reverse):
    details = alternate_balance(position_builder, boundary, reverse)
    result = position_builder.derive()
    # The conflicting archive is not unseen/unlinked: it is cited by this result.
    assert details['alternative_hash'] in result['positions'][0]['sources']
    record_output(f'R10_{boundary}_reverse_{reverse}_direct.json', {'inputs': details, 'result': result})
    assert_unknown_hold(result)


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('reverse', [False, True])
def test_conflicting_token_boundaries_cannot_survive_report_rebuild_api(
        position_builder, boundary, reverse, tmp_path, monkeypatch):
    details = alternate_balance(position_builder, boundary, reverse)
    report = _rebuild_via_api(position_builder, tmp_path, monkeypatch)
    # The helper verifies preserved parent, unchanged usage, zero provider calls,
    # false qualification, and all wallet-level gates UNKNOWN before returning.
    result = report['coverage']['position_evidence']
    assert details['alternative_hash'] in result['positions'][0]['sources']
    record_output(f'R10_{boundary}_reverse_{reverse}_api.json', {'inputs': details, 'report': report})
    assert_unknown_hold(result)
