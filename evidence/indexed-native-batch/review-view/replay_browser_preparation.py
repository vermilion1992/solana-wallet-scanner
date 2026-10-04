"""Independent offline runner preparation replay; never starts a server/browser."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('review_product_browser', ROOT / 'tools/product_browser.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReachedLauncher(Exception):
    pass


class FakeSocket:
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def bind(self, address):
        assert address == ('127.0.0.1', 0)
    def getsockname(self):
        return ('127.0.0.1', 9999)


def main():
    result_path = Path(sys.argv[1])
    checks = []
    with tempfile.TemporaryDirectory(dir=result_path.parent) as temporary:
        base = Path(temporary)
        for indexed in (False, True):
            archive = base / 'indexed-byte-archive.zip'
            archive.write_bytes(b'independent-opaque-preparation-input')
            args = SimpleNamespace(output=base / ('with-indexed' if indexed else 'without-indexed'),
                python=sys.executable, real_corpus=base/'absent-optional-corpus',
                indexed_archive=archive if indexed else None,
                indexed_expected_fees='0.008904733' if indexed else None,
                chromium='must-not-be-launched')
            with patch.object(MODULE.subprocess, 'run') as preparation, \
                 patch.object(MODULE.subprocess, 'Popen', side_effect=ReachedLauncher) as launch, \
                 patch.object(MODULE.socket, 'socket', return_value=FakeSocket()):
                try:
                    MODULE.run(args)
                except ReachedLauncher:
                    pass
                else:
                    raise AssertionError('Preparation did not reach the deliberately disabled launcher')
                receipt = json.loads((args.output/'result.json').read_bytes())
                assert receipt['state'] == 'INCOMPLETE' and receipt['real_acceptance'] == 'BLOCKED'
                assert preparation.call_count == 1, 'Missing optional real corpus must not be packed'
                assert launch.call_count == 1
                if indexed:
                    assert (args.output/'indexed-input.zip').read_bytes() == archive.read_bytes()
                checks.append({'id': 'absent-optional-real-corpus-'+('indexed' if indexed else 'synthetic-only'),
                    'passing': True, 'pack_preparation_commands_mocked': preparation.call_count,
                    'actual_processes_launched': 0, 'socket_bind_mocked': True,
                    'indexed_bytes_copied': indexed, 'producer_receipt_remains_INCOMPLETE': True})
    receipt = {'kind': 'read-only-browser-preparation-replay', 'state': 'PASS_IN_SCOPE',
        'engineering_controls': len(checks), 'checks': checks, 'provider_requests': 0,
        'credential_lookups': 0, 'browser_executed': False, 'network_requests': 0,
        'scope': 'Preparation branch regression control only; not application or browser acceptance.'}
    result_path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
