"""Shared pytest fixtures. Unit tests do not need a 2 GB live-run disk reserve."""
from __future__ import annotations

import os
import shutil

import pytest


@pytest.fixture(autouse=True)
def _unit_tests_do_not_need_live_disk_reserve(monkeypatch):
    """Tests that are not checking the disk gate should not fail on a small volume.

    Live paid runs still default to a 2048 MB reserve. A test that wants that
    gate sets SCANNER_MIN_FREE_DISK_MB itself (see test_disk_refuse_before_paid_request).
    """
    if os.environ.get("SCANNER_MIN_FREE_DISK_MB") in (None, ""):
        monkeypatch.setenv("SCANNER_MIN_FREE_DISK_MB", "0")


def skip_if_low_disk(path, need_mb=256):
    """Skip tests that actually write large artifacts when the volume is too small."""
    probe = path if getattr(path, "exists", lambda: True)() else getattr(path, "parent", path)
    try:
        free = shutil.disk_usage(probe).free
    except OSError as error:
        pytest.skip(f"cannot measure free disk at {probe}: {error}")
        return
    if free < need_mb * 1024 * 1024:
        pytest.skip(
            f"free disk {free} bytes at {probe} is below {need_mb} MB; "
            "re-run with TMPDIR=/dev/shm or free space"
        )
