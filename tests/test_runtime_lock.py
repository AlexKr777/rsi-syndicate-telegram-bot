from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from src.core.runtime_lock import AlreadyRunningError, SingleInstanceLock


class RuntimeLockTests(unittest.TestCase):
    def test_is_process_alive_detects_current_process(self) -> None:
        lock = SingleInstanceLock(Path(tempfile.gettempdir()) / "runtime-lock-self-check.lock")
        self.assertTrue(lock._is_process_alive(os.getpid()))

    def test_second_instance_is_blocked_while_first_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bot.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)

            first.acquire()
            try:
                with self.assertRaises(AlreadyRunningError):
                    second.acquire()
            finally:
                first.release()

    def test_lock_from_previous_boot_is_treated_as_stale(self) -> None:
        class ReusedPidLock(SingleInstanceLock):
            def __init__(self, path: Path, boot_time: float) -> None:
                super().__init__(path)
                self.boot_time = boot_time

            def _is_process_alive(self, pid: int) -> bool:
                return True

            def _boot_time(self) -> float | None:
                return self.boot_time

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bot.lock"
            path.write_text("1234", encoding="utf-8")
            now = time.time()
            os.utime(path, (now - 120, now - 120))

            lock = ReusedPidLock(path, boot_time=now - 60)
            lock.acquire()
            try:
                self.assertEqual(path.read_text(encoding="utf-8"), str(os.getpid()))
            finally:
                lock.release()


if __name__ == "__main__":
    unittest.main()
