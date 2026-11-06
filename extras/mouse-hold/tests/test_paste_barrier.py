import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from autofill import Autofill
from fill_worker import listener_barrier


class BarrierTests(TestCase):
    def test_missing_listener_ack_disallows_paste(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(listener_barrier(Path(folder), Mock()))

    def test_timeout_does_not_allow_paste(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "barrier-window").write_text("42")
            (folder / "barrier-token").write_text("123")
            connection = Mock()
            connection.intern_atom.return_value = 77
            with patch("fill_worker.time.monotonic", side_effect=[0, 1]):
                self.assertFalse(listener_barrier(folder, connection))
            connection.create_resource_object.return_value.send_event.assert_called_once()
            connection.sync.assert_called_once()

    def test_valid_marker_requires_matching_ack_after_sync(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "barrier-window").write_text("42")
            (folder / "barrier-token").write_text("4294967295")
            connection = Mock()
            connection.intern_atom.return_value = 77
            connection.sync.side_effect = lambda: (
                folder / "barrier-ack").write_text("4294967295")
            self.assertTrue(listener_barrier(folder, connection))
            marker = connection.create_resource_object.return_value.send_event.call_args.args[0]
            self.assertEqual(marker.client_type, 77)
            self.assertEqual(marker.data, (32, [4294967295, 0, 0, 0, 0]))

    def test_input_received_during_marker_sync_prevents_paste(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "barrier-window").write_text("42")
            (folder / "barrier-token").write_text("123")
            connection = Mock()
            connection.intern_atom.return_value = 77
            def sync():
                (folder / "invalid").touch()
                (folder / "barrier-ack").write_text("123")
            connection.sync.side_effect = sync
            self.assertFalse(listener_barrier(folder, connection))

    def test_invalidation_even_with_ack_disallows_paste(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name, value in (("barrier-window", "42"), ("barrier-token", "123"),
                                ("barrier-ack", "123"), ("invalid", "")):
                (folder / name).write_text(value)
            self.assertFalse(listener_barrier(folder, Mock()))

    def test_manager_only_acknowledges_its_own_live_token(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Autofill(runtime=folder, barrier_window=42)
            with patch("autofill.subprocess.Popen", return_value=Mock()) as spawn:
                spawn.return_value.poll.return_value = None
                manager.press(1, 2)
                job = manager.current
                token = int((job.directory / "barrier-token").read_text())
                manager.ack_barrier(token + 1)
                self.assertFalse((job.directory / "barrier-ack").exists())
                manager.ack_barrier(token)
                self.assertEqual((job.directory / "barrier-ack").read_text(), str(token))
                manager.close()
