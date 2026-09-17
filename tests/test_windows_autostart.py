from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from src.tools.windows_autostart import (
    LAUNCHER_FILE_NAME,
    autostart_status,
    sync_windows_autostart,
)


def decoded_launcher_command(launcher: Path) -> str:
    text = launcher.read_text(encoding="utf-8")
    encoded = text.split("-EncodedCommand ", 1)[1].splitlines()[0].strip()
    return base64.b64decode(encoded).decode("utf-16le")


class WindowsAutostartTests(unittest.TestCase):
    def test_sync_creates_launcher_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            startup = Path(temp_dir) / "startup"
            root.mkdir()
            startup.mkdir()
            (root / ".env").write_text("AUTO_START_ON_BOOT=true\n", encoding="utf-8")

            enabled, launcher = sync_windows_autostart(root=root, startup_root=startup)

            self.assertTrue(enabled)
            self.assertEqual(launcher, startup / LAUNCHER_FILE_NAME)
            self.assertTrue(launcher.exists())
            raw = launcher.read_bytes()
            text = raw.decode("utf-8")
            decoded_command = decoded_launcher_command(launcher)
            self.assertIn("powershell.exe", text)
            self.assertIn(f"Set-Location -LiteralPath '{root.resolve()}'", decoded_command)
            self.assertIn(
                f"& '{(root / 'run_on_windows_startup.bat').resolve()}'",
                decoded_command,
            )
            self.assertNotIn(b"\r\r\n", raw)

    def test_launcher_is_ascii_safe_for_non_ascii_project_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "что-то важное" / "repo"
            startup = Path(temp_dir) / "startup"
            root.mkdir(parents=True)
            startup.mkdir()
            (root / ".env").write_text("AUTO_START_ON_BOOT=true\n", encoding="utf-8")

            _, launcher = sync_windows_autostart(root=root, startup_root=startup)

            raw = launcher.read_bytes()
            raw.decode("ascii")
            decoded_command = decoded_launcher_command(launcher)
            self.assertNotIn("что-то важное".encode("utf-8"), raw)
            self.assertIn(str(root.resolve()), decoded_command)

    def test_sync_removes_launcher_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            startup = Path(temp_dir) / "startup"
            root.mkdir()
            startup.mkdir()
            (root / ".env").write_text("AUTO_START_ON_BOOT=false\n", encoding="utf-8")
            launcher = startup / LAUNCHER_FILE_NAME
            launcher.write_text("@echo off\n", encoding="utf-8")

            enabled, target = sync_windows_autostart(root=root, startup_root=startup)

            self.assertFalse(enabled)
            self.assertEqual(target, launcher)
            self.assertFalse(launcher.exists())

    def test_status_reports_expected_launcher_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "repo"
            startup = Path(temp_dir) / "startup"
            root.mkdir()
            startup.mkdir()
            (root / ".env").write_text("AUTO_START_ON_BOOT=false\n", encoding="utf-8")
            launcher = startup / LAUNCHER_FILE_NAME
            launcher.write_text("@echo off\n", encoding="utf-8")

            enabled, installed, target = autostart_status(root=root, startup_root=startup)

            self.assertFalse(enabled)
            self.assertTrue(installed)
            self.assertEqual(target, launcher)


if __name__ == "__main__":
    unittest.main()
