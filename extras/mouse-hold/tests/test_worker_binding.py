"""Check both paste paths without a microphone, clipboard, or real window."""
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from fill_worker import run


class WorkerBindingTests(TestCase):
    def test_both_paste_modes_bind_listener_and_invalidation_checks(self):
        for mode in ("window", "terminal"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                (directory / "stopped").touch()
                target = Mock(mode=mode)
                with patch("fill_worker.capture_target", return_value=target), \
                     patch("owned_clipboard.OwnedClipboard"), \
                     patch("fill_worker.read_result", return_value=("skip", "")), \
                     patch("fill_worker.time.sleep"), \
                     patch("fill_worker.listener_barrier", return_value=True) as barrier:
                    self.assertEqual(run(directory, 1, 2, isolated=True), 0)
                    self.assertTrue(target.barrier())
                    barrier.assert_called_once_with(directory, target.display)
                    self.assertTrue(target.guard())
                    (directory / "invalid").touch()
                    self.assertFalse(target.guard())
                    (directory / "invalid").unlink()
                    (directory / "cancelled").touch()
                    self.assertFalse(target.guard())
