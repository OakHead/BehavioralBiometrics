"""Rounded app dialogs and a dimmed desktop for activity verification."""
import ctypes
from ctypes import wintypes
import os
import tkinter as tk
from types import SimpleNamespace
from branding import load_logo
from ui_theme import BG, PANEL, TEXT, MUTED, ACCENT, RED, HERO, BORDER, VIOLET, TITLE_FONT, BODY_FONT, Surface, Button, Check, field


def show_dimmer(window):
    window.overrideredirect(True)
    window.configure(bg='#070610')
    window.attributes('-alpha', .88, '-topmost', True)
    window.geometry(f'{window.winfo_screenwidth()}x{window.winfo_screenheight()}+0+0')
    window.deiconify()
    window.update_idletasks()
    if os.name == 'nt':
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, *([ctypes.c_int]*4), wintypes.UINT]
        user.SetWindowPos.restype = wintypes.BOOL
        frame = user.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
        bounds = [user.GetSystemMetrics(metric) for metric in (76, 77, 78, 79)]
        if bounds[2] > 0 and bounds[3] > 0:
            user.SetWindowPos(frame, -1, *bounds, 0x0010)  # Keep the dimmer from taking focus.


class Dialog(tk.Toplevel):
    def __init__(self, parent, title, message, *, question=False, entry=False, secret=False, error=False,
                 desktop_alert=False, code=None, test=False):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None
        self.question, self.has_entry, self.desktop_alert = question, entry, desktop_alert
        self.parent = parent
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        if desktop_alert:
            self.overrideredirect(True)
            self.attributes('-topmost', True)
        elif parent.winfo_viewable():
            self.transient(parent)
        width = min(560 if desktop_alert else 500, max(320, self.winfo_screenwidth()-72))
        self.content = Surface(self, padding=24, radius=20, border=VIOLET if desktop_alert else BORDER)
        self.content.pack(fill='both', expand=True, padx=12, pady=12)
        body = self.content.body
        heading = tk.Frame(body, bg=PANEL)
        heading.pack(fill='x')
        self.logo = load_logo(self, 30)
        if self.logo is not None:
            tk.Label(heading, image=self.logo, bg=PANEL).pack(side='left', padx=(0, 12))
        self.heading = tk.Label(heading, text=title, bg=PANEL, fg=RED if error else TEXT,
                                font=(TITLE_FONT, 21), wraplength=width-130, anchor='w', justify='left')
        self.heading.pack(side='left', fill='x', expand=True)
        self.message_label = tk.Label(body, text=message, bg=PANEL, fg=MUTED,
                                     font=(BODY_FONT, 11), wraplength=width-84, justify='left', anchor='w')
        self.message_label.pack(fill='x', pady=(18, 16))
        self.code_panel = None
        if code is not None:
            self.code_panel = Surface(body, color=HERO, radius=14, padding=12)
            self.code_panel.pack(fill='x')
            verification = self.code_panel.body
            tk.Label(verification, text=code, bg=HERO, fg=ACCENT,
                     font=(TITLE_FONT, 35)).pack()
            tk.Label(verification, text='Enter this code on your paired phone.', bg=HERO, fg=TEXT,
                     font=(BODY_FONT, 10)).pack()
        self.value = tk.StringVar(self)
        self.entry = None
        if entry:
            self.input_shell, self.entry = field(body, self.value, show='*' if secret else '')
            self.input_shell.pack(fill='x')
            if secret:
                self.show_password = tk.BooleanVar(self)
                self.password_toggle = Check(body, 'Show password', self.show_password,
                                             lambda: self.entry.configure(show='' if self.show_password.get() else '*'))
                self.password_toggle.pack(fill='x', pady=(6, 0))
        buttons = tk.Frame(body, bg=PANEL)
        buttons.pack(fill='x', pady=(20, 0))
        positive = 'Continue' if entry else 'Yes' if question else 'OK'
        if desktop_alert:
            positive = 'Yes, it’s me'
        self.accept_button = Button(buttons, positive, command=self.submit, kind='primary', width=120)
        self.accept_button.pack(side='right')
        if entry or question:
            negative = ('No' if test else 'No, lock PC') if desktop_alert else 'Cancel' if entry else 'No'
            self.cancel_button = Button(buttons, negative, command=self.cancel, kind='danger' if desktop_alert and not test else 'secondary',
                                        width=126 if desktop_alert else 104)
            self.cancel_button.pack(side='right', padx=(0, 10))
        if not desktop_alert:
            self.bind('<Return>', lambda event: self.submit())
        self.bind('<Escape>', lambda event: self.cancel())
        self.geometry(f'{width}x300')
        self.update_idletasks()
        height = max(220, self.content.body.winfo_reqheight()+72)
        x = parent.winfo_rootx()+(parent.winfo_width()-width)//2
        y = parent.winfo_rooty()+(parent.winfo_height()-height)//2
        if desktop_alert or not parent.winfo_viewable():
            x, y = (self.winfo_screenwidth()-width)//2, (self.winfo_screenheight()-height)//2
        x = max(12, min(x, self.winfo_screenwidth()-width-12))
        y = max(12, min(y, self.winfo_screenheight()-height-48))
        self.geometry(f'{width}x{height}+{x}+{y}')

    def show(self):
        previous_grab = self.grab_current()
        previous_focus = self.parent.focus_get()
        dimmer = None
        try:
            if self.desktop_alert:
                dimmer = tk.Toplevel(self.parent)
                dimmer.withdraw()
                show_dimmer(dimmer)
            if self.winfo_exists():
                self.deiconify()
                self.lift()
                self.update_idletasks()
                if not self.winfo_viewable():
                    self.wait_visibility()
                self.grab_set()
                if self.desktop_alert:
                    self.focus_force()
                else:
                    (self.entry or self.accept_button).focus_set()
                self.wait_window()
        finally:
            if dimmer is not None and dimmer.winfo_exists():
                dimmer.destroy()
        if previous_grab is not None and previous_grab.winfo_exists():
            previous_grab.grab_set()
        if previous_focus is not None and previous_focus.winfo_exists():
            previous_focus.focus_set()
        return self.result

    def submit(self):
        self.result = self.value.get() if self.has_entry else True
        self._finish()

    def cancel(self):
        self.result = None if self.has_entry else False
        self._finish()

    def _finish(self):
        self.value.set('')
        self.grab_release()
        self.destroy()


def askstring(title, prompt, parent=None, show=None, **kwargs):
    return Dialog(parent or tk._default_root, title, prompt, entry=True, secret=bool(show)).show()


def askyesno(title, message, parent=None, **kwargs):
    return Dialog(parent or tk._default_root, title, message, question=True,
                  desktop_alert=kwargs.get('desktop_alert', False)).show()


def showinfo(title, message, parent=None, **kwargs):
    Dialog(parent or tk._default_root, title, message).show()


def showerror(title, message, parent=None, **kwargs):
    Dialog(parent or tk._default_root, title, message, error=True).show()


messagebox = SimpleNamespace(askyesno=askyesno, showinfo=showinfo, showerror=showerror)
simpledialog = SimpleNamespace(askstring=askstring)
