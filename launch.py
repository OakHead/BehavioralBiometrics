"""Visible, responsive startup before importing the AI dependencies."""
import ctypes
from ctypes import wintypes
import faulthandler
import hashlib
import importlib
import os
from pathlib import Path
import queue
import threading
import time
import traceback
from branding import APP_NAME, STARTUP_TITLE

BASE = Path(__file__).resolve().parent
DATA = BASE/'data'


class InstanceLock:
    def __init__(self, name):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateMutexW(None, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.first = ctypes.get_last_error() != 183

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def show_existing_window():
    user = ctypes.windll.user32
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    for title in (APP_NAME, STARTUP_TITLE):
        handle = user.FindWindowW(None, title)
        if handle:
            user.ShowWindow(handle, 9)
            user.SetForegroundWindow(handle)
            return


class Starter:
    def __init__(self, root, directory=DATA, loader=None):
        import tkinter as tk
        from tkinter import ttk
        from branding import load_logo, set_icon
        from ui_theme import configure, Surface, PANEL, TEXT, LAVENDER, RED, TITLE_FONT, BODY_FONT
        self.root, self.directory = root, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.loader = loader or (lambda: importlib.import_module('app'))
        self.results = queue.Queue()
        self.started = time.monotonic()
        self.ready = self.failed = False
        root.title(STARTUP_TITLE)
        configure(root)
        width, height = 510, 235
        root.geometry(f'{width}x{height}+{max(0, (root.winfo_screenwidth()-width)//2)}+{max(0, (root.winfo_screenheight()-height)//2)}')
        self.frame = Surface(root, padding=24)
        self.frame.pack(fill='both', expand=True, padx=12, pady=12)
        body = self.frame.body
        set_icon(root)
        heading = tk.Frame(body, bg=PANEL)
        heading.pack(fill='x')
        self.logo = load_logo(root, 42)
        if self.logo is not None:
            tk.Label(heading, image=self.logo, bg=PANEL).pack(side='left', padx=(0, 10))
        tk.Label(heading, text=APP_NAME, bg=PANEL, fg=LAVENDER,
                 font=(TITLE_FONT, 23)).pack(side='left')
        self.status = tk.StringVar(value='Getting the app ready...')
        self.status_label = tk.Label(body, textvariable=self.status, bg=PANEL, fg=TEXT,
                                    wraplength=420, justify='left', font=(BODY_FONT, 11))
        self.status_label.pack(anchor='w', pady=(12, 10))
        self.error_color = RED
        self.bar = ttk.Progressbar(body, mode='indeterminate', style='Enroll.Horizontal.TProgressbar')
        self.bar.pack(fill='x', pady=4)
        self.bar.start(12)
        root.lift()
        root.after(100, self.start_worker)

    def record(self, text):
        try:
            with (self.directory/'startup.log').open('a', encoding='utf-8') as log:
                log.write(time.strftime('%Y-%m-%d %H:%M:%S')+'  '+text+'\n')
        except OSError:
            pass

    def start_worker(self):
        self.record('Loading window opened; importing AI tools.')

        def load():
            try:
                self.results.put((self.loader(), None))
            except BaseException:
                self.results.put((None, traceback.format_exc()))

        threading.Thread(target=load, daemon=True, name='BehaviorGuard-startup').start()
        self.root.after(50, self.poll)

    def fail(self, detail):
        self.failed = True
        self.bar.stop()
        self.status_label.configure(fg=self.error_color)
        try:
            with (self.directory/'startup-error.log').open('a', encoding='utf-8') as log:
                log.write(time.strftime('%Y-%m-%d %H:%M:%S')+'\n'+detail+'\n')
            location = 'Details are in data/startup-error.log.'
        except OSError:
            location = 'The error log could not be saved.'
        self.record('Startup failed. See startup-error.log.')
        reason = detail.strip().splitlines()[-1] if detail.strip() else 'Unknown error.'
        self.status.set(f'Could not start {APP_NAME}.\n'+reason+'\n'+location)

    def poll(self):
        try:
            module, error = self.results.get_nowait()
        except queue.Empty:
            if time.monotonic()-self.started > 12:
                self.status.set('Still starting. Please wait a moment...')
            self.root.after(50, self.poll)
            return
        if error:
            self.fail(error)
            return
        try:
            self.bar.stop()
            self.frame.pack_forget()
            self.application = module.App(self.root)
            self.frame.destroy()
            self.ready = True
            self.record(f'App opened in {time.monotonic()-self.started:.1f} seconds.')
            self.root.lift()
        except BaseException:
            self.frame.pack(fill='both', expand=True)
            self.fail(traceback.format_exc())


def main():
    lock = None
    try:
        DATA.mkdir(exist_ok=True)
        if os.name == 'nt':
            name = 'Local\\BehaviorGuard-'+hashlib.sha256(str(BASE).lower().encode()).hexdigest()[:24]
            lock = InstanceLock(name)
            if not lock.first:
                show_existing_window()
                return
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            except (AttributeError, OSError):
                ctypes.windll.user32.SetProcessDPIAware()
        import tkinter as tk
        with (DATA/'fatal-errors.log').open('a', encoding='utf-8') as fatal_log:
            faulthandler.enable(file=fatal_log)
            root = tk.Tk()
            Starter(root)
            root.mainloop()
            faulthandler.disable()
    except BaseException:
        detail = traceback.format_exc()
        try:
            (DATA/'startup-error.log').write_text(detail, encoding='utf-8')
        except OSError:
            pass
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, f'{APP_NAME} could not start. See data/startup-error.log for details.', APP_NAME, 16)
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    main()
