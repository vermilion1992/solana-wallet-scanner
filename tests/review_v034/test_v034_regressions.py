"""Ordinary fail-closed regressions. All activity is synthetic, never mainnet."""
from copy import deepcopy
import json,os
from pathlib import Path
import pytest
from tests import test_position_evidence as pb
from tests.review_v033.review_helpers import position_builder,failed_middle,assert_unknown_hold
from tests.review_v033.test_v033_regressions import _rebuild_via_api
from scanner.history_evidence import derive_history_evidence


def conflicting_slot(builder, native_slot):
    """Preserve both pages' slot 101, but archive a contradictory raw slot."""
    failed_middle(builder,timestamp=pb.START+3*3600)
    signature='synthetic-review-failed'
    old=builder.cp['transactions'][signature]['evidence_hash']
    raw=builder.store.evidence(old)
    raw['slot']=native_slot
    digest=builder.store.archive(raw)
    builder.cp['transactions'][signature]['evidence_hash']=digest
    for record in builder.records:
        if record['signature']==signature:record['evidence_hash']=digest
    for ref in builder.cp['evidence']:
        if ref.get('kind')=='transaction' and ref.get('signature')==signature:ref['hash']=digest
    builder.persist()
    return signature


@pytest.mark.parametrize('native_slot',[99,103])
def test_conflicting_raw_slot_cannot_exclude_potentially_intervening_receipt(position_builder,native_slot):
    signature=conflicting_slot(position_builder,native_slot)
    history=derive_history_evidence(position_builder.store,pb.WALLET,pb.WINDOW,
              checkpoint=position_builder.cp,collected={'transactions':position_builder.records})
    assert any(c['signature']==signature and c['field']=='slot' for c in history['paging']['conflicts'])
    # Pages place it between the opening (100) and closing (102). No consistent
    # canonical order proves the receipt belongs outside this episode.
    assert_unknown_hold(position_builder.derive())


@pytest.mark.parametrize('native_slot',[99,103])
def test_conflicting_slot_cannot_be_skipped_by_frozen_report_rebuild_api(position_builder,native_slot,tmp_path,monkeypatch):
    conflicting_slot(position_builder,native_slot)
    report=_rebuild_via_api(position_builder,tmp_path,monkeypatch)
    # This helper also checks retained original, unchanged usage, UNKNOWN wallet
    # gates, false qualification, and zero provider requests.
    output=os.environ.get('REVIEW_OUTPUT')
    if output:
        Path(output).mkdir(parents=True,exist_ok=True)
        (Path(output)/f'R9_synthetic_slot_{native_slot}_api_report.json').write_text(json.dumps(report,indent=2))
    assert_unknown_hold(report['coverage']['position_evidence'])
