"""Offline observability tool controls; these do not certify wallet accounting."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

import tools.benchmark_report as benchmark


@pytest.mark.parametrize('seconds', ('0', '301'))
def test_cli_rejects_out_of_contract_watchdog_before_worker_execution(tmp_path, monkeypatch, seconds):
    archive = tmp_path / 'input.zip'
    archive.write_bytes(b'input-not-executed')
    monkeypatch.setattr(sys, 'argv', ['benchmark_report.py', '--archive', str(archive),
        '--output', str(tmp_path / 'output'), '--timeout', seconds])
    monkeypatch.setattr(benchmark.subprocess, 'run', lambda *_a, **_k: pytest.fail('Invalid timeout launched a worker'))
    with pytest.raises(SystemExit) as error:
        benchmark.main()
    assert error.value.code == 2
    assert not (tmp_path / 'output').exists()


def test_outer_timeout_retains_raw_log_and_never_reports_success(tmp_path, monkeypatch):
    archive, output = tmp_path / 'input.zip', tmp_path / 'output'
    archive.write_bytes(b'input-not-executed')
    monkeypatch.setattr(sys, 'argv', ['benchmark_report.py', '--archive', str(archive),
        '--output', str(output), '--timeout', '1'])
    original_run = benchmark.subprocess.run
    def timeout(command, **kwargs):
        if command[0] == 'git':
            return original_run(command, **kwargs)
        assert kwargs['timeout'] == 1 and command[1] == '-c' and 'main(_worker=True)' in command[2]
        kwargs['stdout'].write(b'Simulated watchdog control; no application worker executed.\n')
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(benchmark.subprocess, 'run', timeout)
    assert benchmark.main() == 124
    receipt = json.loads((output / 'command.json').read_text())
    assert receipt['exit_code'] is None and receipt['timed_out'] is True
    assert receipt['acceptance_run'] is False and receipt['observations'] is None
    raw = (output / 'benchmark.log').read_bytes()
    assert receipt['raw_log']['sha256'] == hashlib.sha256(raw).hexdigest()


def test_output_inside_repository_is_rejected_without_creating_private_state(tmp_path, monkeypatch):
    archive = tmp_path / 'input.zip'
    archive.write_bytes(b'input-not-executed')
    output = benchmark.ROOT / 'benchmark-negative-control-output'
    assert not output.exists()
    monkeypatch.setattr(sys, 'argv', ['benchmark_report.py', '--archive', str(archive), '--output', str(output)])
    monkeypatch.setattr(benchmark.subprocess, 'run', lambda *_a, **_k: pytest.fail('Rejected output launched a command'))
    with pytest.raises(SystemExit) as error:
        benchmark.main()
    assert error.value.code == 2 and not output.exists()


def test_optimized_python_cli_is_rejected_before_private_runtime_creation(tmp_path):
    archive, output = tmp_path / 'input.zip', tmp_path / 'output'
    archive.write_bytes(b'input-not-executed')
    command = [sys.executable, '-O', str(Path(benchmark.__file__).resolve()),
               '--archive', str(archive), '--output', str(output)]
    observed = subprocess.run(command, capture_output=True, timeout=10, text=True)
    assert observed.returncode == 2 and '-O disables benchmark guards' in observed.stderr
    assert not output.exists()


def test_public_cli_cannot_select_internal_worker_even_with_a_handwritten_context(tmp_path):
    archive, output = tmp_path / 'input.zip', tmp_path / 'output'
    archive.write_bytes(b'input-not-executed')
    output.mkdir()
    args = SimpleNamespace(archive=archive, timeout=300, profile=False, full_details=False)
    (output / 'worker-context.json').write_text(json.dumps(benchmark.worker_context(args)))
    command = [sys.executable, str(Path(benchmark.__file__).resolve()), '--worker',
               '--archive', str(archive), '--output', str(output)]
    observed = subprocess.run(command, capture_output=True, timeout=10, text=True)
    assert observed.returncode == 2 and 'unrecognized arguments: --worker' in observed.stderr
    assert not (output / 'private-runtime').exists()


@pytest.mark.parametrize('attempt', ('credential', 'transport', 'socket'))
def test_worker_denies_external_attempt_and_saves_nonacceptance_failure(tmp_path, monkeypatch, attempt):
    import scanner.app as application
    archive, output = tmp_path / 'input.zip', tmp_path / 'output'
    archive.write_bytes(b'negative-control-not-an-acceptance-archive')
    output.mkdir()
    monkeypatch.setattr(benchmark, 'source_identity', lambda: {'commit': 'test-control', 'source_sha256': '0' * 64})
    def attempted_create_app(*_args):
        if attempt == 'credential':
            sys.modules['keyring'].get_password('unsigned-control', 'no-secret')
        elif attempt == 'transport':
            with httpx.Client() as client:
                client.get('https://offline-control.invalid/')
        else:
            with socket.socket() as connection:
                connection.connect(('127.0.0.1', 1))
        pytest.fail('Forbidden attempt was not blocked')
    monkeypatch.setattr(application, 'create_app', attempted_create_app)
    args = SimpleNamespace(output=output, archive=archive, profile=False, full_details=False, timeout=300)
    assert benchmark.worker(args) == 1
    receipt = json.loads((output / 'observations.json').read_text())
    assert receipt['state'] == 'FAILED'
    assert receipt['calls'][attempt] == 1
    assert sum(receipt['calls'].values()) == 1
    assert receipt['acceptance_run'] is False and receipt['product_readiness_claim'] is False
    assert receipt['error']['type'] == 'AssertionError'
