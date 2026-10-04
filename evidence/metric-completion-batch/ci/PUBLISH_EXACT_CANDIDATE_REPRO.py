#!/usr/bin/env python3
"""Transfer approved Git objects through GitHub's API, preserving every SHA."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path('/workspace/solana-wallet-scanner')
OUT = Path('/workspace/outputs/metric-completion-publication')
REPO = 'vermilion1992/solana-wallet-scanner'
BRANCH = 'codex/product-completion'
EXPECTED_APPLICATION = '7e4769922ad8055b8c290f7625401d8a42fd183b'
EXPECTED_SOURCE = '578029f5d9a608e62b1336889b52e90025831732aeec2cea087a1dd8d57d7ee2'
sys.path.insert(0, str(ROOT))
from tools.repository_audit import audit
from tools.validate import source_manifest

ENV = {k: v for k, v in os.environ.items() if k not in
       ('HELIUS_API_KEY', 'GH_DEBUG', 'GIT_TRACE', 'GIT_TRACE_CURL',
        'GIT_CURL_VERBOSE', 'GIT_TRACE_PACKET')}
JOURNAL = OUT / 'EXACT_OBJECT_IMPORT.json'
if not JOURNAL.exists():
    JOURNAL.write_bytes(Path('/workspace/outputs/genuine-wallet-publication/EXACT_OBJECT_IMPORT.json').read_bytes())
state = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {
    'kind': 'exact-private-git-object-import', 'repository': REPO,
    'verified_objects': [], 'api_requests': 0, 'force_push': False,
    'history_squashed': False, 'helius_probe_executed': False,
    'product_ready': False}
assert state['repository'] == REPO
known = {(row['type'], row['sha']) for row in state['verified_objects']}
known_blobs = {sha for kind, sha in known if kind == 'blob'}
initialized = json.loads((Path('/workspace/outputs/b2-git-publication') / 'API_INITIALIZATION.json').read_text())
assert initialized['exit_code'] == 0
known_blobs.add(initialized['response']['blob_sha'])
last_write = 0.0


def save():
    temporary = JOURNAL.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(JOURNAL)


def git(*argv):
    return subprocess.check_output(['git', *argv], cwd=ROOT, env=ENV)


def api(method, endpoint, body=None):
    global last_write
    if method != 'GET':
        # Serialize writes and remain below ordinary secondary write limits.
        delay = 1.0 - (time.monotonic() - last_write)
        if delay > 0:
            time.sleep(delay)
        last_write = time.monotonic()
    command = ['gh', 'api', '--method', method, endpoint]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as stream:
        if body is not None:
            json.dump(body, stream, ensure_ascii=False)
            stream.flush()
            command += ['--input', stream.name]
        result = subprocess.run(command, cwd=ROOT, env=ENV,
                                capture_output=True, text=True, timeout=120)
    state['api_requests'] += 1
    if result.returncode:
        raise RuntimeError(f'{method} {endpoint}: {result.stderr.strip()}')
    return json.loads(result.stdout)


def verify(kind, expected, response):
    if response.get('sha') != expected:
        raise RuntimeError(f'{kind} identity mismatch: expected {expected}, returned {response.get("sha")}')
    if (kind, expected) not in known:
        known.add((kind, expected))
        state['verified_objects'].append({'type': kind, 'sha': expected})
    if kind == 'blob':
        known_blobs.add(expected)
    save()
    print(json.dumps({'verified_objects': len(known), 'type': kind, 'sha': expected}), flush=True)


def private_destination():
    metadata = api('GET', 'repos/' + REPO)
    if (metadata.get('full_name') != REPO or metadata.get('private') is not True
            or metadata.get('permissions', {}).get('push') is not True):
        raise RuntimeError('Exact private destination with write access was not confirmed')
    return metadata


def blob(sha, raw):
    if sha in known_blobs:
        return
    response = api('POST', 'repos/' + REPO + '/git/blobs',
                   {'content': base64.b64encode(raw).decode(), 'encoding': 'base64'})
    verify('blob', sha, response)


def tree(sha):
    if ('tree', sha) in known:
        return
    rows = git('ls-tree', '-z', sha).split(b'\0')
    elements, inline = [], []
    for row in rows:
        if not row:
            continue
        header, name = row.split(b'\t', 1)
        mode, kind, identifier = header.decode().split()
        entry = {'path': name.decode('utf-8'), 'mode': '040000' if mode == '040000' else mode,
                 'type': kind}
        if kind == 'tree':
            tree(identifier)
            entry['sha'] = identifier
        elif kind == 'blob':
            if identifier in known_blobs:
                entry['sha'] = identifier
            else:
                raw = git('cat-file', 'blob', identifier)
                try:
                    content = raw.decode('utf-8')
                except UnicodeDecodeError:
                    content = None
                if content is None or len(raw) > 128 * 1024:
                    blob(identifier, raw)
                    entry['sha'] = identifier
                else:
                    entry['content'] = content
                    inline.append((entry, identifier, raw))
        else:
            raise RuntimeError('Unexpected external Git-link object; do not substitute history')
        elements.append(entry)
    # Keep inline tree payloads small; binary/large blobs have separate uploads.
    while len(json.dumps({'tree': elements}, ensure_ascii=False).encode()) > 4 * 1024 * 1024:
        if not inline:
            raise RuntimeError('Tree request exceeds the bounded payload size')
        entry, identifier, raw = max(inline, key=lambda item: len(item[2]))
        inline.remove((entry, identifier, raw))
        blob(identifier, raw)
        entry.pop('content')
        entry['sha'] = identifier
    response = api('POST', 'repos/' + REPO + '/git/trees', {'tree': elements})
    verify('tree', sha, response)
    # Equal tree SHA binds names, modes and every inline blob SHA exactly.
    for _, identifier, _ in inline:
        known_blobs.add(identifier)
        if ('blob', identifier) not in known:
            known.add(('blob', identifier))
            state['verified_objects'].append({'type': 'blob', 'sha': identifier,
                                              'proof': 'exact containing tree SHA'})
    save()


def person(value):
    match = re.fullmatch(r'(.*) <(.*)> ([0-9]+) ([+-][0-9]{4})', value)
    if not match or match[4] != '+0000':
        raise RuntimeError('Commit author/date cannot be represented without changing identity')
    return {'name': match[1], 'email': match[2],
            'date': datetime.fromtimestamp(int(match[3]), timezone.utc).isoformat()}


def commit(sha):
    if ('commit', sha) in known:
        return
    raw = git('cat-file', 'commit', sha)
    headers, message = raw.decode('utf-8').split('\n\n', 1)
    values, parents = {}, []
    for line in headers.splitlines():
        key, value = line.split(' ', 1)
        if key == 'parent':
            if ('commit', value) not in known:
                raise RuntimeError('Parent is not yet preserved remotely')
            parents.append(value)
        elif key in ('tree', 'author', 'committer'):
            values[key] = value
        else:
            raise RuntimeError('Unsupported commit header; do not rewrite history')
    tree(values['tree'])
    response = api('POST', 'repos/' + REPO + '/git/commits', {
        'tree': values['tree'], 'parents': parents, 'message': message,
        'author': person(values['author']), 'committer': person(values['committer'])})
    verify('commit', sha, response)


try:
    metadata = private_destination()
    source_path = ROOT / 'evidence/metric-completion-batch/SOURCE_MANIFEST.json'
    gates_path = ROOT / 'evidence/metric-completion-batch/FINAL_GATES.json'
    source_bytes, gates_bytes = source_path.read_bytes(), gates_path.read_bytes()
    expected_source, gates = json.loads(source_bytes), json.loads(gates_bytes)
    if gates.get('application_commit') != EXPECTED_APPLICATION or gates.get('source_sha256') != EXPECTED_SOURCE or expected_source.get('sha256') != EXPECTED_SOURCE:
        raise RuntimeError('Exact reviewed application/source pins do not match')
    head = git('rev-parse', 'HEAD').decode().strip()
    if gates.get('state') != 'SCOPED_PASS_REAL_ACCEPTANCE_BLOCKED' or gates.get('PRODUCT_READY') is not False:
        raise RuntimeError('Final scoped gates and explicit genuine block are required before publication')
    current = source_manifest(ROOT)
    if current != expected_source:
        raise RuntimeError('Validated source changed; do not publish stale evidence')
    changed = git('diff', '--name-only', gates['application_commit'], 'HEAD').decode().splitlines()
    if any(not p.startswith(('evidence/metric-completion-batch/',)) for p in changed):
        raise RuntimeError('Evidence HEAD changes application source after validation')
    if git('branch', '--show-current').decode().strip() != BRANCH or git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Candidate branch must be clean and committed')
    if git('rev-list', '--all', '--not', 'HEAD'):
        raise RuntimeError('Additional local history requires preservation before import')
    def unchanged_candidate():
        if (git('rev-parse', 'HEAD').decode().strip() != head
                or git('branch', '--show-current').decode().strip() != BRANCH
                or git('status', '--porcelain', '--untracked-files=no')
                or source_manifest(ROOT) != expected_source
                or source_path.read_bytes() != source_bytes
                or gates_path.read_bytes() != gates_bytes):
            raise RuntimeError('Candidate or validated receipts changed; stop publication')
    unchanged_candidate()
    checked = audit(ROOT)
    (OUT / 'PRE_PUSH_AUDIT.json').write_text(json.dumps(checked, indent=2) + '\n')
    if checked['state'] != 'PASS':
        raise RuntimeError('Secret/history audit did not pass')
    if checked.get('head') != head or checked.get('branch') != BRANCH:
        raise RuntimeError('Audit does not bind the exact candidate HEAD/branch')
    unchanged_candidate()
    private_destination()
    commits = git('rev-list', '--reverse', '--topo-order', head).decode().splitlines()
    if len(commits) > 100:
        raise RuntimeError('Unexpected history size; reassess bounded import')
    state.update(state='IMPORTING', head=head, source_sha256=current['sha256'],
                 audit_counts=checked['counts'], local_commit_count=len(commits))
    save()
    for sha in commits:
        commit(sha)
    # Inspect the ref without suppressing authorization failures.
    branches = api('GET', 'repos/' + REPO + '/branches?per_page=100')
    existing = next((row for row in branches if row['name'] == BRANCH), None)
    unchanged_candidate()
    private_destination()
    if existing:
        old = existing['commit']['sha']
        if old != head:
            git('merge-base', '--is-ancestor', old, head)
            response = api('PATCH', 'repos/' + REPO + '/git/refs/heads/' + BRANCH,
                           {'sha': head, 'force': False})
        else:
            response = api('GET', 'repos/' + REPO + '/git/ref/heads/' + BRANCH)
    else:
        response = api('POST', 'repos/' + REPO + '/git/refs',
                       {'ref': 'refs/heads/' + BRANCH, 'sha': head})
    if response.get('object', {}).get('sha') != head:
        raise RuntimeError('Implementation ref identity mismatch')
    # Existing integration cannot administer the default branch. Explicit
    # candidate branch publication only; no settings mutation or extra retry.
    metadata = private_destination()
    for sha in ('a811e81aa2d46807d50915f47193a99f890eb854',
                'b1296c1952f94ac67dcd63792eb845129cb48b1b', head):
        if api('GET', 'repos/' + REPO + '/git/commits/' + sha).get('sha') != sha:
            raise RuntimeError('Preserved commit not available through GitHub')
    if source_manifest(ROOT) != current or git('rev-parse', 'HEAD').decode().strip() != head:
        raise RuntimeError('Local candidate changed during publication')
    git('update-ref', 'refs/remotes/origin/' + BRANCH, head)
    git('config', 'branch.' + BRANCH + '.remote', 'origin')
    git('config', 'branch.' + BRANCH + '.merge', 'refs/heads/' + BRANCH)
    state.update(state='PUBLISHED_AND_VERIFIED', remote_head=head,
                 url=metadata['html_url'], private=True, branch=BRANCH,
                 default_branch=metadata['default_branch'], source_unchanged=True,
                 publication_method='GitHub Git Database API, exact object/commit SHAs',
                 initialization_branch_retained='main; bootstrap README only')
    save()
    print(json.dumps({k: v for k, v in state.items() if k != 'verified_objects'}), flush=True)
except Exception as exc:
    state.update(state='BLOCKED', reason=type(exc).__name__ + ': ' + str(exc))
    save()
    print(json.dumps({'state': 'BLOCKED', 'reason': state['reason']}), flush=True)
    raise SystemExit(2)
