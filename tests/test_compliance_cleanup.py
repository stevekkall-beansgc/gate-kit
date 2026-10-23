"""Real, disposable process trees exercise legacy timeout/cancellation cleanup."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import compliance


@unittest.skipUnless(os.name == "posix", "the supported runners are POSIX")
class TestCheckCleanup(unittest.TestCase):
    def _descendant(self, *, parent_exits=False, cancelled=False,
                    runner=None, timeout=900):
        runner = runner or compliance.sh
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # The child ignores TERM and is bounded even if the assertion or
            # runner fails. It writes only inside this disposable directory.
            child = (
                "import os, signal, time\n"
                "from pathlib import Path\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "Path('ready').write_text(str(os.getpid()))\n"
                "deadline = time.monotonic() + 3\n"
                "while not Path('release').exists() and time.monotonic() < deadline:\n"
                "    time.sleep(0.01)\n"
                "if Path('release').exists():\n"
                "    Path('survived').write_text('ran after the check stopped')\n"
            )
            parent = ("import subprocess, sys, time\n"
                      f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                      + ("" if parent_exits else "time.sleep(10)\n"))
            real_communicate = subprocess.Popen.communicate

            def bounded_communicate(process, *args, **kwargs):
                self.assertEqual(kwargs["timeout"], timeout)
                deadline = time.monotonic() + 3
                while not (root / "ready").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((root / "ready").exists(), "disposable child did not start")
                if cancelled:
                    raise KeyboardInterrupt
                return real_communicate(process, *args, **{**kwargs, "timeout": 0.1})

            try:
                with mock.patch.object(subprocess.Popen, "communicate", bounded_communicate):
                    if cancelled:
                        with self.assertRaises(KeyboardInterrupt):
                            runner([sys.executable, "-c", parent], root)
                    else:
                        result = runner([sys.executable, "-c", parent], root)
                        self.assertEqual(set(result), {"ok", "secs", "tail"})
                        self.assertFalse(result["ok"])
                        self.assertEqual(result["tail"], f"timeout {timeout}s")
                        self.assertLess(result["secs"], 5)
            finally:
                # On the old implementation the orphan acknowledges this file
                # and immediately exits, so a failing-first run leaves no worker.
                (root / "release").touch()
                time.sleep(0.4)
            self.assertFalse((root / "survived").exists(),
                             "a descendant kept running after timeout/cancellation")

    def test_timeout_stops_descendants_that_ignore_term(self):
        self._descendant()

    def test_timeout_stops_descendants_after_the_parent_exits(self):
        self._descendant(parent_exits=True)

    def test_interruption_stops_descendants_and_propagates(self):
        self._descendant(cancelled=True)


if __name__ == "__main__":
    unittest.main()
