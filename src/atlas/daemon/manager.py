"""Daemon process management -- PID file and lifecycle."""

import os
from pathlib import Path


class PidFile:
    def __init__(self, path: str):
        self._path = Path(path)

    def write(self, pid: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(str(pid))

    def read(self) -> int | None:
        if not self._path.exists():
            return None
        try:
            return int(self._path.read_text().strip())
        except (ValueError, OSError):
            self.remove()
            return None

    def is_running(self) -> bool:
        pid = self.read()
        if pid is None:
            return False
        if not _pid_exists(pid):
            self.remove()
            return False
        return True

    def remove(self) -> None:
        self._path.unlink(missing_ok=True)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it
