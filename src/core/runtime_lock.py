from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        if pid is not None:
            super().__init__(f"Another RSI bot instance is already running (pid={pid}).")
        else:
            super().__init__("Another RSI bot instance is already running.")


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.pid = os.getpid()
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                existing_pid = self._read_pid()
                if self._is_from_previous_boot():
                    self.path.unlink(missing_ok=True)
                    continue
                if existing_pid is not None and not self._is_process_alive(existing_pid):
                    self.path.unlink(missing_ok=True)
                    continue
                raise AlreadyRunningError(existing_pid)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(str(self.pid))
                    handle.flush()
            except Exception:
                self.path.unlink(missing_ok=True)
                raise
            self._acquired = True
            return

    def release(self) -> None:
        if not self._acquired:
            return
        current_pid = self._read_pid()
        if current_pid == self.pid:
            self.path.unlink(missing_ok=True)
        self._acquired = False

    def _read_pid(self) -> int | None:
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError:
            return None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _is_process_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _is_from_previous_boot(self) -> bool:
        boot_time = self._boot_time()
        if boot_time is None:
            return False
        try:
            return self.path.stat().st_mtime < boot_time
        except OSError:
            return False

    def _boot_time(self) -> float | None:
        if os.name != "nt":
            return None
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetTickCount64.restype = ctypes.c_ulonglong
            uptime_seconds = kernel32.GetTickCount64() / 1000
            return time.time() - uptime_seconds
        except Exception:
            return None
