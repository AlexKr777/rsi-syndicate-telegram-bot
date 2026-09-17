from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path


AUTO_START_FLAG = "AUTO_START_ON_BOOT"
STARTUP_DIR_OVERRIDE = "RSI_STARTUP_DIR"
LAUNCHER_FILE_NAME = "RSI Bot AutoStart.cmd"
REPO_STARTUP_RUNNER = "run_on_windows_startup.bat"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def env_file_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().upper()] = value.strip()
    return values


def parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def startup_dir() -> Path:
    override = os.environ.get(STARTUP_DIR_OVERRIDE)
    if override:
        return Path(override).expanduser()
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set, cannot resolve the Windows Startup folder.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def launcher_path(*, startup_root: Path | None = None) -> Path:
    return (startup_root or startup_dir()) / LAUNCHER_FILE_NAME


def powershell_string(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def encoded_startup_command(*, root: Path | None = None) -> str:
    project_root = (root or repo_root()).resolve()
    runner_path = project_root / REPO_STARTUP_RUNNER
    command = "\r\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            f"Set-Location -LiteralPath {powershell_string(project_root)}",
            f"& {powershell_string(runner_path)}",
            "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }",
            "exit 0",
        )
    )
    return base64.b64encode(command.encode("utf-16le")).decode("ascii")


def launcher_contents(*, root: Path | None = None) -> str:
    encoded_command = encoded_startup_command(root=root)
    return (
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
        "-NoProfile -ExecutionPolicy Bypass -EncodedCommand "
        f"{encoded_command}\r\n"
        "exit /b %ERRORLEVEL%\r\n"
    )


def autostart_enabled(*, root: Path | None = None) -> bool:
    env_values = parse_env_file(env_file_path(root))
    return parse_bool(env_values.get(AUTO_START_FLAG))


def sync_windows_autostart(
    *,
    root: Path | None = None,
    startup_root: Path | None = None,
) -> tuple[bool, Path]:
    enabled = autostart_enabled(root=root)
    target = launcher_path(startup_root=startup_root)
    if enabled:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(launcher_contents(root=root).encode("utf-8"))
    elif target.exists():
        target.unlink()
    return enabled, target


def autostart_status(
    *,
    root: Path | None = None,
    startup_root: Path | None = None,
) -> tuple[bool, bool, Path]:
    enabled = autostart_enabled(root=root)
    target = launcher_path(startup_root=startup_root)
    return enabled, target.exists(), target


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync Windows autostart for the RSI bot.")
    parser.add_argument(
        "command",
        nargs="?",
        default="sync",
        choices=("sync", "status"),
        help="sync creates/removes the Startup launcher, status prints the current state.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "status":
        enabled, installed, target = autostart_status()
        print(
            f"AUTO_START_ON_BOOT={'true' if enabled else 'false'}; "
            f"launcher={'present' if installed else 'missing'}; "
            f"path={target}"
        )
        return 0

    enabled, target = sync_windows_autostart()
    state = "enabled" if enabled else "disabled"
    print(f"Windows autostart is {state}. Launcher path: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
