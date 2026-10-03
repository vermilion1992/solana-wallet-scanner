import json
import pytest
from tools import publish_private as publisher


@pytest.mark.parametrize('privacy', [False, 'true', None])
def test_public_or_unverified_privacy_cannot_dispatch_push(monkeypatch, privacy):
    calls = []
    def fake(argv):
        calls.append(argv)
        if argv[:3] == ['git', 'branch', '--show-current']:
            return publisher.BRANCH
        if argv[:2] == ['gh', 'api']:
            return json.dumps({'full_name': 'owner/scanner', 'private': privacy,
                               'permissions': {'push': True}, 'html_url': 'https://github.com/owner/scanner'})
        return ''
    monkeypatch.setattr(publisher, 'run', fake)
    monkeypatch.setattr(publisher, 'audit', lambda _: {'state': 'PASS', 'counts': {}})
    with pytest.raises(ValueError, match='private'):
        publisher.publish('owner/scanner', push=True)
    assert not any('push' in call for call in calls)
    assert not any(call[:3] == ['git', 'remote', 'add'] for call in calls)


def test_unrelated_destination_or_missing_push_access_is_not_published(monkeypatch):
    def fake(argv):
        if argv[:3] == ['git', 'branch', '--show-current']:
            return publisher.BRANCH
        if argv[:2] == ['gh', 'api']:
            return json.dumps({'full_name': 'owner/scanner', 'private': True, 'permissions': {'push': False}})
        return ''
    monkeypatch.setattr(publisher, 'run', fake)
    monkeypatch.setattr(publisher, 'audit', lambda _: {'state': 'PASS', 'counts': {}})
    with pytest.raises(ValueError, match='push access'):
        publisher.publish('owner/scanner', push=True)
    with pytest.raises(ValueError, match='exact destination'):
        publisher.publish('different/scanner', push=True)


def test_blocked_secret_audit_prevents_even_repository_metadata_request(monkeypatch):
    calls = []
    def fake(argv):
        calls.append(argv)
        return publisher.BRANCH if argv[:3] == ['git', 'branch', '--show-current'] else ''
    monkeypatch.setattr(publisher, 'run', fake)
    monkeypatch.setattr(publisher, 'audit', lambda _: {'state': 'BLOCKED', 'counts': {}})
    with pytest.raises(ValueError, match='audit is blocked'):
        publisher.publish('owner/scanner', push=True)
    assert not any(call[0] == 'gh' or 'push' in call for call in calls)


def test_dirty_candidate_cannot_be_published(monkeypatch):
    def fake(argv):
        return publisher.BRANCH if argv[:3] == ['git', 'branch', '--show-current'] else ' M scanner/app.py'
    monkeypatch.setattr(publisher, 'run', fake)
    with pytest.raises(ValueError, match='committed and clean'):
        publisher.publish('owner/scanner', push=True)
