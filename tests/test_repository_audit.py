import gzip
import io
import json
import subprocess
import zipfile

import pytest

from tools.repository_audit import audit, inspect_bytes, sensitive_path


def scan(raw):
    findings = []
    inspect_bytes(raw, 'fixture', findings, {'text_payloads': 0})
    return findings


@pytest.mark.parametrize('path', ['.env.local', 'credentials/helius.json', 'private.sqlite3-wal', 'keyring/provider.key'])
def test_runtime_secret_paths_are_sensitive(path):
    assert sensitive_path(path)


def test_source_fixtures_and_placeholder_environment_samples_are_preserved():
    assert not sensitive_path('.env.example')
    assert not sensitive_path('tests/fixtures/mainnet-wrapper-0.json')
    assert not sensitive_path('evidence/references/helius-billing-nav.gz')
    assert not scan(b'https://example.invalid/?api-key=your-api-key-here')


def test_nested_raw_input_credentials_block_without_echoing_the_value():
    value = 'a' * 8 + '-' + '-'.join(['b' * 4] * 3) + '-' + 'c' * 12
    raw = gzip.compress(json.dumps({'api_key': value}).encode())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('archives/input.json.gz', raw)
    findings = scan(buffer.getvalue())
    assert any(x['rule'] == 'literal-api-credential' for x in findings)
    assert value not in json.dumps(findings)


def test_private_key_and_keypair_arrays_block():
    assert scan(('-----BEGIN ' + 'PRIVATE KEY-----').encode())
    assert scan(json.dumps(list(range(64))).encode())


def test_opaque_literal_credential_is_blocked_in_an_environment_sample():
    value = 'q' * 32
    assert any(x['rule'] == 'literal-opaque-credential' for x in scan(('API_KEY="' + value + '"').encode()))
    assert not scan(b'API_KEY = os.environ.get("PROVIDER_KEY")')


def test_removed_historical_credential_still_blocks_push(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q')
    git('config', 'user.name', 'Audit test')
    git('config', 'user.email', 'audit@example.invalid')
    (tmp_path / '.gitignore').write_text('.env*\ncredentials/\nkeyring/\n*.db*\n*.sqlite*\nlocal-data/\n.solana/\n')
    token = 'gh' + 'p_' + 'a' * 36
    (tmp_path / 'removed.txt').write_text(token)
    git('add', '.')
    git('commit', '-qm', 'historical fixture')
    (tmp_path / 'removed.txt').unlink()
    git('add', '-u')
    git('commit', '-qm', 'remove file')
    record = audit(tmp_path, require_corpus=False)
    assert record['state'] == 'BLOCKED'
    assert any(x['rule'] == 'github-token' and x['path'].startswith('history:') for x in record['findings'])
    assert token not in json.dumps(record)


def test_untracked_runtime_guard_and_missing_corpus_cannot_pass(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=Audit test', '-c', 'user.email=audit@example.invalid',
                    'commit', '--allow-empty', '-qm', 'fixture'], cwd=tmp_path, check=True)
    record = audit(tmp_path)
    rules = {x['rule'] for x in record['findings']}
    assert record['state'] == 'BLOCKED'
    assert 'runtime-path-not-ignored' in rules
    assert 'required-replay-corpus-not-tracked' in rules
