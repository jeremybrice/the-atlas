import os
from atlas.daemon.manager import PidFile


def test_pidfile_write_and_read(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(12345)
    assert pf.read() == 12345
    assert pf.is_running() is False  # PID 12345 unlikely to exist


def test_pidfile_remove(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(os.getpid())
    assert pf.read() == os.getpid()
    pf.remove()
    assert pf.read() is None


def test_pidfile_stale_detection(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(99999999)  # non-existent PID
    assert pf.is_running() is False
    assert pf.read() is None  # auto-cleaned stale PID


def test_pidfile_current_process(tmp_path):
    pf = PidFile(str(tmp_path / "test.pid"))
    pf.write(os.getpid())
    assert pf.is_running() is True
