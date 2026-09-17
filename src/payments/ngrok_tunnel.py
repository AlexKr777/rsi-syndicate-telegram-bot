from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from src.core.config import Settings

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class NgrokTunnelStatus:
    public_base_url: str | None
    webhook_url: str | None
    error: str | None = None


class NgrokTunnelManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._process: asyncio.subprocess.Process | None = None
        self._log_task: asyncio.Task | None = None

    async def start(self) -> NgrokTunnelStatus:
        if not self.settings.ngrok_enabled:
            return NgrokTunnelStatus(public_base_url=None, webhook_url=None, error="ngrok_disabled")

        existing_status = await self._probe_existing_tunnel()
        if existing_status is not None:
            LOGGER.info("Reusing existing ngrok tunnel public_base_url=%s", existing_status.public_base_url)
            return existing_status

        executable = self._resolve_ngrok_executable()
        if executable is None:
            return NgrokTunnelStatus(
                public_base_url=None,
                webhook_url=None,
                error=(
                    f"ngrok executable was not found. Install ngrok or set NGROK_EXE / NGROK_PATH. "
                    f"Current NGROK_EXE={self.settings.ngrok_exe or '(empty)'} "
                    f"NGROK_PATH={self.settings.ngrok_path or '(empty)'}"
                ),
            )

        args = [str(executable), "http", str(self.settings.local_webhook_port)]
        config_path = self._resolve_ngrok_config_path()
        if self.settings.ngrok_config_path is not None and config_path is None:
            return NgrokTunnelStatus(
                public_base_url=None,
                webhook_url=None,
                error=f"ngrok config file was not found: {self.settings.ngrok_config_path}",
            )
        if config_path is not None:
            args.extend(["--config", str(config_path)])
        LOGGER.info(
            "Starting ngrok executable=%s port=%s config=%s",
            executable,
            self.settings.local_webhook_port,
            config_path or "default",
        )
        if self.settings.ngrok_authtoken.strip():
            args.extend(["--authtoken", self.settings.ngrok_authtoken.strip()])
        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._log_task = asyncio.create_task(self._capture_logs(), name="ngrok-log-capture")
        status = await self._wait_for_public_url()
        if status.public_base_url:
            LOGGER.info("ngrok tunnel ready public_base_url=%s", status.public_base_url)
        else:
            LOGGER.warning("ngrok tunnel did not become ready: %s", status.error)
        return status

    async def stop(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
        if self._log_task is not None:
            self._log_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._log_task
            self._log_task = None

    def _resolve_ngrok_executable(self) -> Path | None:
        configured = self.settings.resolved_ngrok_executable.strip()
        if configured:
            found = shutil.which(configured)
            if found:
                return Path(found)
            candidate = Path(configured).expanduser()
            if candidate.exists():
                return candidate
        found = shutil.which("ngrok")
        return Path(found) if found else None

    def _resolve_ngrok_config_path(self) -> Path | None:
        configured = self.settings.ngrok_config_path
        if configured is not None:
            return configured if configured.exists() else None
        local_app_data = Path.home()
        try:
            import os

            local_app_data = Path(os.environ.get("LocalAppData") or local_app_data)
        except Exception:
            pass
        default_config = local_app_data / "ngrok" / "ngrok.yml"
        return default_config if default_config.exists() else None

    async def _capture_logs(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    LOGGER.debug("ngrok | %s", text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.debug("ngrok log capture stopped: %s", exc)

    async def _probe_existing_tunnel(self) -> NgrokTunnelStatus | None:
        api_url = f"{self.settings.ngrok_api_base_url.rstrip('/')}/api/tunnels"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                async with session.get(api_url) as response:
                    if response.status != 200:
                        return None
                    payload = await response.json(content_type=None)
        except Exception:
            return None
        public_url = self._extract_public_url(payload)
        if not public_url:
            return None
        return NgrokTunnelStatus(
            public_base_url=public_url,
            webhook_url=f"{public_url.rstrip('/')}{self.settings.normalized_crypto_pay_webhook_path}",
        )

    async def _wait_for_public_url(self) -> NgrokTunnelStatus:
        deadline = asyncio.get_running_loop().time() + max(self.settings.ngrok_start_timeout_seconds, 3)
        api_url = f"{self.settings.ngrok_api_base_url.rstrip('/')}/api/tunnels"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            while asyncio.get_running_loop().time() < deadline:
                if self._process is not None and self._process.returncode not in {None, 0}:
                    return NgrokTunnelStatus(
                        public_base_url=None,
                        webhook_url=None,
                        error=f"ngrok exited early with code {self._process.returncode}",
                    )
                try:
                    async with session.get(api_url) as response:
                        if response.status == 200:
                            payload = await response.json(content_type=None)
                            public_url = self._extract_public_url(payload)
                            if public_url:
                                return NgrokTunnelStatus(
                                    public_base_url=public_url,
                                    webhook_url=f"{public_url.rstrip('/')}{self.settings.normalized_crypto_pay_webhook_path}",
                                )
                except Exception:
                    pass
                await asyncio.sleep(1.0)
        return NgrokTunnelStatus(
            public_base_url=None,
            webhook_url=None,
            error="ngrok API did not report an https tunnel before timeout",
        )

    def _extract_public_url(self, payload: dict[str, object]) -> str | None:
        tunnels = payload.get("tunnels")
        if not isinstance(tunnels, list):
            return None
        target_addr = f"http://localhost:{self.settings.local_webhook_port}"
        fallback: str | None = None
        for item in tunnels:
            if not isinstance(item, dict):
                continue
            public_url = item.get("public_url")
            if not isinstance(public_url, str) or not public_url.startswith("https://"):
                continue
            config = item.get("config")
            if isinstance(config, dict):
                addr = str(config.get("addr") or "")
                if addr in {target_addr, f"http://127.0.0.1:{self.settings.local_webhook_port}", str(self.settings.local_webhook_port)}:
                    return public_url
            if fallback is None:
                fallback = public_url
        return fallback
