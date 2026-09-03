"""DeckyLoader backend for GameSphere Import Tool."""

import asyncio
import os
import re
import shutil
import subprocess

import decky


INSTALL_DIR = os.path.expanduser("~/.local/share/gamesphere-import-tool")
BIN_CANDIDATES = [
    os.path.expanduser("~/.local/bin/gamesphere-import"),
    os.path.join(INSTALL_DIR, "main.py"),
]


def _resolve_command() -> list[str] | None:
    for candidate in BIN_CANDIDATES:
        if candidate.endswith("main.py") and os.path.isfile(candidate):
            uv = shutil.which("uv")
            if uv:
                return [uv, "run", candidate]
            python = shutil.which("python3") or shutil.which("python")
            if python:
                return [python, candidate]
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return [candidate]
    return None


def _run_sync(args: list[str], timeout: int = 600) -> tuple[bool, str, str | None]:
    cmd = _resolve_command()
    if not cmd:
        return False, "GameSphere Import CLI not found. Run scripts/install-linux.sh on the host.", None

    full = cmd + args
    decky.logger.info("Running: %s", " ".join(full))
    try:
        result = subprocess.run(
            full,
            cwd=INSTALL_DIR if os.path.isdir(INSTALL_DIR) else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        banner = None
        match = re.search(r"^BANNER:(.+)$", output, re.MULTILINE)
        if match:
            banner = match.group(1).strip()
        ok = result.returncode == 0
        if not ok and not output.strip():
            output = f"Exit code {result.returncode}"
        return ok, output.strip(), banner
    except subprocess.TimeoutExpired:
        return False, "Import timed out after 10 minutes.", None
    except Exception as exc:
        return False, str(exc), None


class Plugin:
    async def get_status(self):
        installed = _resolve_command() is not None
        paths = {}
        if installed:
            ok, output, _ = await asyncio.get_event_loop().run_in_executor(
                None, lambda: _run_sync(["--print-config"], timeout=30)
            )
            if ok:
                paths = {"raw": output}
        return {"installed": installed, "paths": paths}

    async def run_import(self, dry_run: bool = True):
        args = ["--dry-run"] if dry_run else []
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(args)
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def run_remove(self):
        ok, output, banner = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_sync(["--remove-games"])
        )
        return {"ok": ok, "output": output, "banner": banner}

    async def _main(self):
        decky.logger.info("GameSphere Import Decky plugin loaded")

    async def _unload(self):
        pass

    async def _uninstall(self):
        pass
