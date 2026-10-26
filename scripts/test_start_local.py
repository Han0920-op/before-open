"""Launcher checks without Docker, package downloads, or model calls."""

import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import start_local


class LauncherChecks(unittest.TestCase):
    def test_occupied_port_is_preserved(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            # Check the actual configured port logic, without taking port 8001.
            real_socket = socket.socket

            class OccupiedSocket(real_socket):
                def bind(self, address: tuple[str, int]) -> None:
                    super().bind((address[0], port))

            with (
                patch.object(start_local.socket, "socket", OccupiedSocket),
                self.assertRaisesRegex(start_local.StartupError, "in use"),
            ):
                start_local.check_ports()
            self.assertGreaterEqual(listener.fileno(), 0)

    def test_dependency_change_invalidates_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}")
            (root / "package-lock.json").write_text("old")
            with patch.object(start_local, "FRONTEND", root):
                old = start_local.dependency_fingerprint()
                (root / "package-lock.json").write_text("new")
                self.assertNotEqual(old, start_local.dependency_fingerprint())

    def test_setup_failure_stops_startup(self) -> None:
        launcher = start_local.Launcher()
        try:
            with self.assertRaises(start_local.StartupError):
                launcher.run_step([sys.executable, "-c", "raise SystemExit(7)"], Path.cwd())
        finally:
            launcher.stop()

    def test_cleanup_stops_owned_child(self) -> None:
        launcher = start_local.Launcher()
        child = launcher.spawn([sys.executable, "-c", "import time; time.sleep(60)"], Path.cwd())
        launcher.stop()
        self.assertIsNotNone(child.poll())

    def test_failed_service_is_detected(self) -> None:
        launcher = start_local.Launcher()
        child = launcher.spawn([sys.executable, "-c", "pass"], Path.cwd())
        child.wait(timeout=10)
        launcher.services = [child]
        with self.assertRaises(start_local.StartupError):
            launcher.check_services()

    @unittest.skipUnless(sys.platform == "win32", "Windows-only process tree fallback")
    def test_windows_forced_cleanup_only_targets_owned_pid(self) -> None:
        launcher = start_local.Launcher()
        with patch.object(start_local.subprocess, "Popen") as popen:
            child = popen.return_value
            child.poll.return_value = None
            child.wait.side_effect = [subprocess.TimeoutExpired("owned", 5), 0]
            launcher.children = [child]
            with patch.object(start_local.subprocess, "run") as run:
                launcher.stop()
                self.assertEqual(
                    run.call_args.args[0], ["taskkill", "/PID", str(child.pid), "/T", "/F"]
                )


if __name__ == "__main__":
    unittest.main()
