"""
input_lock.py - global mouse block + keyboard escape-combo block for
DeskGuard's virtual lock overlay.

This does NOT touch any camera or driver code - it installs two
low-level Win32 hooks (WH_MOUSE_LL, WH_KEYBOARD_LL), the same mechanism
legitimate kiosk-mode software uses. It must run on a thread that pumps
Windows messages; VirtualLockOverlay's tkinter mainloop qualifies, since
Tk's event loop on Windows is itself a Windows message loop.

What this blocks
-----------------
- ALL mouse input: movement, every button, the wheel. The cursor is
  also pinned to a 1x1 rect with ClipCursor and hidden with ShowCursor,
  so nothing visibly moves either. There is no partial mode - once
  started, the mouse is completely inert until stop() runs.
- The specific keyboard combos that would let someone get past a
  full-screen always-on-top window without the unlock code:
  the Windows key (Start menu), Alt+Tab (task switcher), Ctrl+Esc
  (Start menu), Ctrl+Shift+Esc (straight to Task Manager), Alt+F4
  (close window).

Every other key - letters, digits, Enter, Backspace, arrow keys - is
passed straight through untouched, so the unlock-code entry field in
the overlay keeps working exactly like a normal text box.

What this CANNOT block, by Windows design
------------------------------------------
Ctrl+Alt+Del. It is the Secure Attention Sequence: Windows routes it
directly to Winlogon on the secure desktop *before* any userland hook
- this one included - ever gets a chance to see it. That is an
intentional floor, not a gap in this implementation: no process,
malicious or not, is allowed to trap a session past it. Someone who
reaches Ctrl+Alt+Del -> Task Manager can still end the DeskGuard
process. This module cannot and does not try to prevent that; see
watchdog.py for how DeskGuard responds to it instead (by detecting the
process dying mid-lock and triggering a real Windows lock as a
fallback, rather than trying to make the process unkillable).
"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105

VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_F4 = 0x73
VK_LMENU = 0xA4  # left Alt
VK_RMENU = 0xA5  # right Alt
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3

# Low-level mouse messages we swallow unconditionally. Covers the main
# buttons, the extra (X1/X2) buttons, both wheel axes, and plain movement.
MOUSE_MESSAGES = {
    0x0200,  # WM_MOUSEMOVE
    0x0201, 0x0202,  # WM_LBUTTONDOWN / UP
    0x0204, 0x0205,  # WM_RBUTTONDOWN / UP
    0x0207, 0x0208,  # WM_MBUTTONDOWN / UP
    0x020A,  # WM_MOUSEWHEEL
    0x020B, 0x020C,  # WM_XBUTTONDOWN / UP
    0x020E,  # WM_MOUSEHWHEEL
}


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class InputLock:
    """Owns both low-level hooks for one virtual-lock session.

    Create one instance per lock, call start() from the overlay thread
    right before entering its message loop, call stop() once the
    correct code is entered (or as a safety net if the overlay window
    goes away through any other path).
    """

    def __init__(self, on_key_activity=None):
        self._kb_hook = None
        self._mouse_hook = None
        self._kb_proc_ref = None   # keep references alive - ctypes will
        self._mouse_proc_ref = None  # garbage-collect the callback otherwise
        self._alt_down = False
        self._ctrl_down = False
        self._cursor_was_clipped = False
        self._cursor_was_hidden = False
        self._on_key_activity = on_key_activity  # optional: fires on any
        # non-blocked keydown, e.g. so the overlay can flash a hint the
        # first time someone touches the keyboard

    # -- keyboard ----------------------------------------------------
    def _keyboard_proc(self, nCode, wParam, lParam):
        if nCode == 0:
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = info.vkCode
            down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)
            up = wParam in (WM_KEYUP, WM_SYSKEYUP)

            if vk in (VK_LMENU, VK_RMENU):
                self._alt_down = down or (self._alt_down and not up)
            if vk in (VK_LCONTROL, VK_RCONTROL):
                self._ctrl_down = down or (self._ctrl_down and not up)

            block = False
            if vk in (VK_LWIN, VK_RWIN):
                block = True                  # Start menu
            elif vk == VK_TAB and self._alt_down:
                block = True                  # Alt+Tab
            elif vk == VK_ESCAPE and self._ctrl_down:
                block = True                  # Ctrl(+Shift)+Esc
            elif vk == VK_F4 and self._alt_down:
                block = True                  # Alt+F4

            if block:
                return 1  # swallow - never reaches the OS or any window

            if down and self._on_key_activity:
                try:
                    self._on_key_activity()
                except Exception:
                    pass  # a callback failure must never break the hook chain

        return user32.CallNextHookEx(self._kb_hook, nCode, wParam, lParam)

    # -- mouse ---------------------------------------------------------
    def _mouse_proc(self, nCode, wParam, lParam):
        if nCode == 0 and wParam in MOUSE_MESSAGES:
            return 1  # swallow every mouse event, no exceptions
        return user32.CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)

    # -- lifecycle -----------------------------------------------------
    def start(self):
        self._kb_proc_ref = LowLevelProc(self._keyboard_proc)
        self._mouse_proc_ref = LowLevelProc(self._mouse_proc)

        self._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc_ref, None, 0)
        self._mouse_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_proc_ref, None, 0)

        if not self._kb_hook or not self._mouse_hook:
            err = ctypes.get_last_error()
            self.stop()
            raise OSError(f"SetWindowsHookExW failed (WinError {err}) - "
                           f"input was NOT locked.")

        rect = wintypes.RECT(0, 0, 1, 1)
        if not user32.ClipCursor(ctypes.byref(rect)):
            self.stop()
            raise OSError("ClipCursor failed - input was NOT locked.")
        self._cursor_was_clipped = True
        user32.ShowCursor(False)
        self._cursor_was_hidden = True

    def stop(self):
        # stop() is intentionally safe to call more than once: the overlay
        # calls it on a successful unlock and again from its finally block.
        if self._cursor_was_clipped:
            user32.ClipCursor(None)
            self._cursor_was_clipped = False
        if self._cursor_was_hidden:
            user32.ShowCursor(True)
            self._cursor_was_hidden = False
        if self._kb_hook:
            user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None
