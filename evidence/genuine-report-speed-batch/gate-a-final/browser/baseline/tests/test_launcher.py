"""The source launcher permits only one active process per local data directory."""
import pytest

from scanner.__main__ import InstanceAlreadyRunning, data_directory_lock


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
