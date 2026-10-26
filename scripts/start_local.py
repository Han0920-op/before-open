"""Single-console local launcher, used by start.bat; never stops the database."""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
LOCAL = ROOT / ".local"
UI_URL = "http://127.0.0.1:5173"


class StartupError(Exception):
    pass


def require_command(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise StartupError(f"Missing {name}. Install the tools listed in docs/QUICKSTART.md.")
    return executable


def check_ports() -> None:
    for port in (8001, 5173):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Windows must not share a port with an existing service.
            if sys.platform == "win32":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                raise StartupError(
                    f"Port {port} is in use. Close the previous launcher or check the "
                    "service using it. No existing processes were stopped."
                ) from None


def dependency_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in ("package.json", "package-lock.json"):
        digest.update((FRONTEND / name).read_bytes())
    digest.update(b"node24")
    return digest.hexdigest()


class Launcher:
    def __init__(self) -> None:
        self.children: list[subprocess.Popen[bytes]] = []
        self.services: list[subprocess.Popen[bytes]] = []
        self.env = os.environ.copy()
        # These overrides apply only to loopback development and its child processes.
        self.env["COOKIE_SECURE"] = "false"
        self.env["BEFORE_OPEN_API_TARGET"] = "http://127.0.0.1:8001"

    def spawn(self, args: list[str], cwd: Path) -> subprocess.Popen[bytes]:
        if sys.platform == "win32":
            process = subprocess.Popen(
                args, cwd=cwd, env=self.env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(args, cwd=cwd, env=self.env, start_new_session=True)
        self.children.append(process)
        return process

    def run_step(self, args: list[str], cwd: Path) -> None:
        if self.spawn(args, cwd).wait() != 0:
            raise StartupError("Setup failed. See the output above; no services were started.")

    def stop(self) -> None:
        for child in reversed(self.children):
            if child.poll() is not None:
                continue
            if sys.platform == "win32":
                # Graceful first, then terminate only this launcher's process tree.
                try:
                    child.send_signal(signal.CTRL_BREAK_EVENT)
                    child.wait(timeout=5)
                    continue
                except (OSError, subprocess.TimeoutExpired):
                    subprocess.run(
                        ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
            else:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=5)
                except ProcessLookupError:
                    pass
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)

    def wait_ready(self, url: str, timeout: float = 60) -> None:
        # Loopback traffic must not go through system HTTP proxies.
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check_services()
            try:
                with opener.open(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                pass
            time.sleep(0.25)
        raise StartupError("Service readiness timed out. See the output above.")

    def check_services(self) -> None:
        if any(child.poll() is not None for child in self.services):
            raise StartupError("A service exited. See the output above; stopping its companion.")

    def start(self) -> None:
        if sys.version_info[:2] != (3, 12):
            raise StartupError("Use Python 3.12 (start.bat selects it automatically via uv).")
        node = require_command("node")
        npm = require_command("npm.cmd" if sys.platform == "win32" else "npm")
        if subprocess.check_output([node, "--version"], text=True).strip().split(".")[0] != "v24":
            raise StartupError("Node.js 24.x is required. Install it and restart this launcher.")
        check_ports()

        # npm.cmd is a batch script; invoke its entry JS directly so paths containing
        # spaces work without shell quoting or launching an extra command window.
        npm_cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if sys.platform == "win32":
            if not npm_cli.is_file():
                raise StartupError("Cannot locate npm-cli.js. Reinstall the official Node.js 24.")
            npm_args = [node, str(npm_cli)]
        else:
            npm_args = [npm]
        LOCAL.mkdir(mode=0o700, exist_ok=True)
        stamp = LOCAL / "frontend-deps.sha256"
        fingerprint = dependency_fingerprint()
        if (
            not (FRONTEND / "node_modules" / "vite" / "bin" / "vite.js").is_file()
            or not stamp.exists()
            or stamp.read_text().strip() != fingerprint
        ):
            print("[Before Open] Installing locked frontend dependencies...", flush=True)
            self.run_step([*npm_args, "ci", "--no-audit", "--no-fund"], FRONTEND)
            stamp.write_text(fingerprint, encoding="ascii")

        if not self.env.get("DATABASE_URL"):
            require_command("docker")
            print("[Before Open] Starting local PostgreSQL (Docker must be running)...", flush=True)
            self.run_step([sys.executable, str(ROOT / "scripts" / "dev_db.py")], ROOT)
        else:
            print("[Before Open] Using DATABASE_URL from your environment (value hidden).")
        print("[Before Open] Applying database migrations...", flush=True)
        self.run_step([sys.executable, "-m", "alembic", "upgrade", "head"], BACKEND)

        print("[Before Open] Starting backend and frontend. Press Ctrl+C here to stop both.")
        api = self.spawn(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", "8001"], BACKEND,
        )
        self.services = [api]
        self.wait_ready("http://127.0.0.1:8001/api/v1/ready")
        ui = self.spawn(
            [node, str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"),
             "--host", "127.0.0.1", "--port", "5173", "--strictPort"], FRONTEND,
        )
        self.services.append(ui)
        self.wait_ready(UI_URL)
        self.wait_ready(f"{UI_URL}/api/v1/ready")
        print(f"[Before Open] Ready: {UI_URL} (database stays running after exit)", flush=True)
        try:
            webbrowser.open(UI_URL)
        except webbrowser.Error:
            print("[Before Open] Open the address above in your browser.")
        while True:
            self.check_services()
            time.sleep(0.5)


def main() -> int:
    launcher = Launcher()
    try:
        launcher.start()
    except KeyboardInterrupt:
        print("\n[Before Open] Stopping frontend and backend...")
    except (StartupError, OSError, subprocess.SubprocessError) as error:
        # Do not include exception messages: third-party commands may contain secrets.
        message = (
            str(error) if isinstance(error, StartupError) else "Command failed; see output above."
        )
        print(f"[ERROR] {message}", file=sys.stderr)
        return 1
    finally:
        # A second Ctrl+C must not interrupt cleanup and leave an orphan server.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, signal.SIG_IGN)
        launcher.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
