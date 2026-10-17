"""core of the osrs bot"""

import sys as _sys

if _sys.platform.startswith("linux"):
    # python-xlib is only thread-safe when Xlib.threaded is imported before any
    # Display is opened (pyautogui opens one at import). The bots read the window,
    # mouse and hover text from several threads at once; without this the X
    # connection gets corrupted ("unpack requires a buffer of 4 bytes") and the
    # bot hangs.
    try:
        import Xlib.threaded  # noqa: F401
    except ImportError:
        pass
