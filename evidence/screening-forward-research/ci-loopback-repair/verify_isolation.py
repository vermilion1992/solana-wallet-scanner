"""Read-only verification of retained CI namespace and source receipts."""
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from tools.validate import source_manifest

receipt = json.loads((HERE / 'RECEIPT.json').read_text())
for name, digest in receipt['evidence_sha256'].items():
    assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest, name
baseline = json.loads((HERE / 'namespace-loopback-baseline.json').read_text())
assert baseline['outcome'] == 'REPRODUCED' and baseline['errno'] == 101
lines = (HERE / 'namespace-loopback-fixed.log').read_text().splitlines()
links, routes = map(json.loads, lines[:2])
assert len(links) == 1 and links[0]['ifname'] == 'lo' and 'UP' in links[0]['flags']
for route in routes:
    assert route.get('dev') == 'lo' and 'gateway' not in route
    network = ipaddress.ip_network(route['dst'], strict=False)
    loopback = ipaddress.ip_network('127.0.0.0/8' if network.version == 4 else '::1/128')
    assert network.subnet_of(loopback)
assert re.search(r'\b2 passed in ', '\n'.join(lines[2:]))
workflow = (ROOT / '.github/workflows/offline-focused.yml').read_text()
wrappers = workflow.split('sudo unshare --net -- \\\n')[1:]
assert len(wrappers) == 3
for wrapper in wrappers:
    assert wrapper.index('ip link set dev lo up') < wrapper.index('setpriv --reuid=')
assert source_manifest(ROOT) == receipt['source_manifest']
changed = subprocess.check_output(['git', 'diff', '--name-only',
    receipt['runtime_equivalence']['from_commit'] + '..' + receipt['runtime_equivalence']['to_commit']],
    cwd=ROOT, text=True).splitlines()
assert changed == receipt['runtime_equivalence']['changed_source_paths']
print(json.dumps({'state': 'PASS', 'interfaces': ['lo'], 'default_routes': 0,
    'nonloopback_routes': 0, 'local_transport_tests': 2,
    'source_sha256': receipt['source_manifest']['sha256'], 'new_live_claim': False}))
