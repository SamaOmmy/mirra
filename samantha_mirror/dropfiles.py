"""Files dragged from Explorer onto a Tk window (Windows only; Tk has no drag and drop of its own).

The window is told to accept files (DragAcceptFiles) and its window procedure is wrapped, so WM_DROPFILES reaches
`on_drop(paths)`; every other message goes to Tk as before. Elsewhere, or if anything here fails, it does nothing.
"""
import logging
import sys

log = logging.getLogger("samantha-mirror")
WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4


def accept_files(tk_window, on_drop) -> bool:
    """Calls on_drop(list of paths) when files are dropped on the window. True if it is set up."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.GetParent.restype = wintypes.HWND
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragFinish.argtypes = [wintypes.HANDLE]

        tk_window.update_idletasks()
        hwnd = user32.GetParent(tk_window.winfo_id()) or tk_window.winfo_id()

        old = [None]   # Tk's own window procedure

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                try:
                    count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    paths = []
                    for i in range(count):
                        size = shell32.DragQueryFileW(wparam, i, None, 0) + 1
                        buf = ctypes.create_unicode_buffer(size)
                        shell32.DragQueryFileW(wparam, i, buf, size)
                        paths.append(buf.value)
                    shell32.DragFinish(wparam)
                    tk_window.after(0, on_drop, paths)
                except Exception:   # never let an error escape into Windows' message loop
                    log.exception("Dropping files failed")
                return 0
            return user32.CallWindowProcW(old[0], h, msg, wparam, lparam)

        callback = WNDPROC(proc)
        old[0] = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
        if not old[0] or not user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p)):
            return False
        tk_window._mirra_drop = callback   # keep it alive as long as the window
        shell32.DragAcceptFiles(hwnd, True)
        return True
    except Exception:
        log.exception("Could not accept dropped files")
        return False
