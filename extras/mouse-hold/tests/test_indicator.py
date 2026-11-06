import unittest
from unittest.mock import Mock, patch
from indicator import prevent_focus, trusted_indicator, prepare_indicator


class IndicatorTests(unittest.TestCase):
    def test_preserves_existing_hints_and_other_protocols(self):
        w = Mock()
        w.get_wm_hints.return_value = {'flags': 66, 'input': 1, 'initial_state': 1}
        w.get_wm_protocols.return_value = [10, 20, 30]
        self.assertTrue(prevent_focus(w, 20))
        hints = w.set_wm_hints.call_args.kwargs
        self.assertEqual(hints, {'flags': 67, 'input': 0, 'initial_state': 1})
        w.set_wm_protocols.assert_called_once_with([10, 30])

    def test_indicator_bypasses_window_manager_activation_on_every_remap(self):
        w = Mock()
        w.get_wm_hints.return_value = {'flags': 1, 'input': 1}
        w.get_wm_protocols.return_value = []
        self.assertTrue(prevent_focus(w, 20))
        w.change_attributes.assert_called_once_with(override_redirect=True)
        w.set_input_focus.assert_not_called()
        w.map.assert_not_called()
        w.unmap.assert_not_called()

    def test_real_xlib_hint_wrapper_is_supported(self):
        from Xlib.protocol.rq import DictWrapper
        w = Mock()
        w.get_wm_hints.return_value = DictWrapper({'flags': 67, 'input': 1, 'initial_state': 1})
        w.get_wm_protocols.return_value = [10, 20]
        self.assertTrue(prevent_focus(w, 20))
        self.assertEqual(w.set_wm_hints.call_args.kwargs['input'], 0)

    def test_no_hints_is_not_a_client_window(self):
        w = Mock()
        w.get_wm_hints.return_value = None
        self.assertFalse(prevent_focus(w, 20))
        w.set_wm_hints.assert_not_called()
        w.set_wm_protocols.assert_not_called()
        w.change_attributes.assert_not_called()

    def test_unchanged_protocols_not_replaced(self):
        w = Mock()
        w.get_wm_hints.return_value = {'flags': 1, 'input': 1}
        w.get_wm_protocols.return_value = [10, 30]
        prevent_focus(w, 20)
        w.set_wm_protocols.assert_not_called()

    def test_window_failure_is_not_silenced(self):
        w = Mock()
        w.get_wm_hints.side_effect = RuntimeError('gone')
        with self.assertRaises(RuntimeError):
            prevent_focus(w, 20)

    def test_only_verified_indicator_windows_are_changed(self):
        connection, root, ordinary, indicator = Mock(), Mock(), Mock(), Mock()
        root.query_tree.return_value.children = [ordinary, indicator]
        for w, pid in [(ordinary, 10), (indicator, 20)]:
            w.query_tree.return_value.children = []
            w.get_full_property.return_value.value = [pid]
        with patch('indicator.trusted_indicator', side_effect=lambda pid: pid == 20), patch('indicator.prevent_focus', return_value=True) as change:
            self.assertEqual(prepare_indicator(connection, root), 1)
            change.assert_called_once_with(indicator, connection.intern_atom.return_value)
        ordinary.set_wm_hints.assert_not_called()
        ordinary.change_attributes.assert_not_called()
        connection.sync.assert_called_once()

    def test_other_binary_is_not_trusted(self):
        with patch('indicator.os.stat') as stat, patch('indicator.os.readlink', return_value='/usr/bin/chrome'):
            stat.return_value.st_uid = 1000
            with patch('indicator.os.getuid', return_value=1000):
                self.assertFalse(trusted_indicator(123))

    def test_other_user_is_not_trusted(self):
        with patch('indicator.os.stat') as stat, patch('indicator.os.getuid', return_value=1000):
            stat.return_value.st_uid = 1001
            self.assertFalse(trusted_indicator(123))
