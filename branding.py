"""Shared app branding; the symbol contains no text or initials."""
from pathlib import Path
import math
import tkinter as tk

APP_NAME = 'Behavioral Guard'
STARTUP_TITLE = f'{APP_NAME} | Starting'
LOGO = Path(__file__).resolve().parent/'assets'/'shield.png'


def load_logo(root, size):
    if not LOGO.exists():
        return None
    original = tk.PhotoImage(master=root, file=str(LOGO))
    factor = max(1, math.ceil(max(original.width(), original.height())/size))
    return original.subsample(factor)


def set_icon(root):
    root._guard_icon = load_logo(root, 64)
    if root._guard_icon is not None:
        root.iconphoto(True, root._guard_icon)
