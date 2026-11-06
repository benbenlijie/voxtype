"""Make only the installed Voxtype indicator non-focusable on X11."""
import os
from pathlib import Path


def trusted_indicator(pid):
    try:
        process = '/proc/%d' % pid
        return (os.stat(process).st_uid == os.getuid()
                and os.readlink(process + '/exe') == str(
                    Path.home() / '.local/lib/voxtype/voxtype-osd-gtk4.bin'))
    except (OSError, ValueError):
        return False


def prevent_focus(window, take_focus):
    """Keep this trusted overlay outside WM activation on every GTK remap."""
    old = window.get_wm_hints()
    if old is None:
        return False  # Do not change GTK's hidden group-leader window.
    # GTK4 rewrites InputHint when showing a hidden window. The WM then
    # activates the OSD despite an earlier input=0. This server-side attribute
    # survives GTK remaps and makes the trusted overlay bypass WM activation.
    # Do not hide/remap a visible window or move/restore the user's focus.
    window.change_attributes(override_redirect=True)
    hints = dict(old if isinstance(old, dict) else old._data)
    hints['flags'] = hints.get('flags', 0) | 1  # InputHint
    hints['input'] = 0
    window.set_wm_hints(**hints)
    protocols = list(window.get_wm_protocols())
    if take_focus in protocols:
        window.set_wm_protocols([p for p in protocols if p != take_focus])
    return True


def prepare_indicator(connection, root):
    from Xlib import X
    changed = 0
    pid_atom = connection.intern_atom('_NET_WM_PID')
    take_focus = connection.intern_atom('WM_TAKE_FOCUS')
    # GTK's actual client window is a direct child while hidden, but can be
    # reparented into a WM frame while mapped. Bound traversal to two levels.
    windows = list(root.query_tree().children)
    for w in list(windows):
        windows.extend(w.query_tree().children)
    for window in windows:
        prop = window.get_full_property(pid_atom, X.AnyPropertyType)
        if prop is None or not len(prop.value):
            continue
        if trusted_indicator(int(prop.value[0])):
            changed += int(prevent_focus(window, take_focus))
    connection.sync()
    return changed
