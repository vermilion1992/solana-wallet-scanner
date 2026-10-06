"""The source launcher permits only one active process per local data directory."""
import pytest

from scanner.__main__ import InstanceAlreadyRunning, data_directory_lock, discover_lan_ipv4
from scanner.lan_qr import encode_matrix, render_ascii


def test_lan_qr_has_finder_patterns_and_is_not_committed_with_a_token():
    matrix = encode_matrix("http://172.30.0.2:8765/#session=example")
    n = len(matrix)
    assert n >= 21
    assert all(matrix[0][i] for i in range(7))
    assert all(matrix[i][0] for i in range(7))
    ascii_qr = render_ascii("http://172.30.0.2:8765/#session=example")
    assert "█" in ascii_qr
    ip = discover_lan_ipv4()
    assert not ip.startswith("127.")


def test_second_lock_is_refused_and_release_allows_restart(tmp_path):
    data = tmp_path / "scanner-data"
    with data_directory_lock(data) as directory:
        assert directory == data
        with pytest.raises(InstanceAlreadyRunning, match="another scanner process"):
            with data_directory_lock(data):
                pytest.fail("a second writer acquired the active data directory")
    # The persistent file does not prevent a clean process restart.
    assert (data / ".runtime.lock").exists()
    with data_directory_lock(data):
        pass


def test_separate_directories_can_run_independently(tmp_path):
    with data_directory_lock(tmp_path / "first"):
        with data_directory_lock(tmp_path / "second"):
            pass


def test_exception_releases_runtime_lock(tmp_path):
    with pytest.raises(RuntimeError, match="startup failed"):
        with data_directory_lock(tmp_path):
            raise RuntimeError("startup failed")
    with data_directory_lock(tmp_path):
        pass


def test_symlinked_runtime_lock_is_rejected_without_modifying_target(tmp_path):
    data = tmp_path / "scanner-data"
    data.mkdir()
    target = tmp_path / "outside"
    target.write_text("preserve me")
    try:
        (data / ".runtime.lock").symlink_to(target)
    except OSError:
        pytest.skip("symbolic links unavailable on this platform")
    with pytest.raises(OSError, match="symbolic link"):
        with data_directory_lock(data):
            pass
    assert target.read_text() == "preserve me"
