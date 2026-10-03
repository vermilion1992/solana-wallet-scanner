#!/usr/bin/env python3
"""Publish preserved history to an existing, API-verified private GitHub repository."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.repository_audit import audit
from tools.validate import source_manifest

APP = 'a811e81aa2d46807d50915f47193a99f890eb854'
PREPARATION = 'b1296c1952f94ac67dcd63792eb845129cb48b1b'
BRANCH = 'codex/product-completion'


def run(argv):
    env = {k: v for k, v in os.environ.items() if k not in
           ('HELIUS_API_KEY', 'GH_DEBUG', 'GIT_TRACE', 'GIT_TRACE_CURL', 'GIT_CURL_VERBOSE', 'GIT_TRACE_PACKET')}
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed with exit {result.returncode}: {result.stderr.strip()}')
    return result.stdout.strip()


def publish(repo, *, push=False):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Use an exact GitHub owner/repository identifier')
    branch = run(['git', 'branch', '--show-current'])
    if branch != BRANCH or run(['git', 'status', '--short', '--untracked-files=no']):
        raise ValueError('The active candidate branch must be committed and clean')
    if any(n and not n.startswith('evidence/') for n in run(['git', 'ls-files', '--others', '--exclude-standard']).splitlines()):
        raise ValueError('Commit untracked implementation files before publishing')
    for baseline in (APP, PREPARATION):
        run(['git', 'merge-base', '--is-ancestor', baseline, 'HEAD'])
    if run(['git', 'rev-list', '--all', '--not', 'HEAD']):
        raise ValueError('Preserve additional local history not reachable from this branch before publication')
    checked = audit(ROOT)
    if checked['state'] != 'PASS':
        raise ValueError('The pre-push secret/history/replay-input audit is blocked')
    metadata = json.loads(run(['gh', 'api', 'repos/' + repo, '--jq', '{full_name,private,html_url,permissions}']))
    if metadata.get('full_name', '').lower() != repo.lower() or metadata.get('private') is not True:
        raise ValueError('GitHub did not confirm the exact destination is private')
    if metadata.get('permissions', {}).get('push') is not True:
        raise ValueError('The connected account/app lacks push access')
    head = run(['git', 'rev-parse', 'HEAD'])
    record = {'kind': 'private-github-publication', 'state': 'PREPARED', 'repository': metadata['full_name'],
              'url': metadata['html_url'], 'private': True, 'branch': branch, 'head': head,
              'tested_application_baseline': APP, 'preparation_baseline': PREPARATION,
              'source': source_manifest(ROOT), 'audit_counts': checked['counts'],
              'history_preserved': True, 'force_push': False, 'product_ready': False, 'helius_probe_executed': False}
    if not push:
        return record
    url = 'https://github.com/' + metadata['full_name'] + '.git'
    if 'origin' in run(['git', 'remote']).splitlines():
        if run(['git', 'remote', 'get-url', 'origin']) != url:
            raise ValueError('Existing origin differs; do not silently replace it')
    else:
        run(['git', 'remote', 'add', 'origin', url])
    run(['git', '-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential',
         'push', '--set-upstream', 'origin', 'HEAD:refs/heads/' + BRANCH])
    remote = json.loads(run(['gh', 'api', 'repos/' + repo + '/git/ref/heads/' + BRANCH, '--jq', '{ref,object}']))
    privacy = json.loads(run(['gh', 'api', 'repos/' + repo, '--jq', '{private,html_url}']))
    if remote.get('object', {}).get('sha') != head or privacy.get('private') is not True:
        raise ValueError('Remote commit/privacy verification failed after push')
    record.update(state='PUSHED_AND_VERIFIED', remote_head=head)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository')
    parser.add_argument('--push', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        record = publish(args.repository, push=args.push)
        code = 0
    except (ValueError, RuntimeError) as exc:
        record = {'kind': 'private-github-publication', 'state': 'BLOCKED', 'reason': str(exc),
                  'requested_repository': args.repository, 'public_repository_created': False, 'helius_probe_executed': False}
        code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({k: v for k, v in record.items() if k != 'source'}))
    raise SystemExit(code)
