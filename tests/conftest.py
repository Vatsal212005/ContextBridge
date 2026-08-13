"""Test-session isolation for ContextBridge runtime state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.gettempdir()) / f"contextbridge_pytest_{os.getpid()}.db"
os.environ["CONTEXTBRIDGE_DB_PATH"] = str(_TEST_DB)


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    for path in [
        _TEST_DB,
        Path(str(_TEST_DB) + "-wal"),
        Path(str(_TEST_DB) + "-shm"),
        _TEST_DB.with_name(_TEST_DB.name + ".action-key"),
    ]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
