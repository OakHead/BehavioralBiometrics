"""Shared colors and rounded Tk controls. No additional packages are required."""
import ctypes
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, font as tkfont

BG = '#0e0d18'
RAIL = '#171422'
PANEL = '#1c1b2d'
FIELD = '#2a2841'
BORDER = '#383450'
TEXT = '#f6f3ff'
MUTED = '#bcb5d0'
ACCENT = '#89e6dd'
AMBER = '#ffd092'
RED = '#ff839e'
HERO = '#271d3d'
VIOLET = '#c4a3ff'
LAVENDER = '#e4d2ff'
BLUE = '#9bb9ff'
TILE = '#212137'
ACTIVE = '#37294e'
FONTS = Path(__file__).resolve().parent/'assets'/'fonts'


def packaged_font(filename, family, fallback):
    path = FONTS/filename
    if os.name == 'nt' and path.is_file():
        register = ctypes.windll.gdi32.AddFontMemResourceEx
        register.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        register.restype = ctypes.c_void_p
        data = path.read_bytes()
        font_count = ctypes.c_uint32()
        # GDI copies the bytes and makes the font private to this process.
        if register(ctypes.create_string_buffer(data), len(data), None, ctypes.byref(font_count)):
            return family
    return fallback


TITLE_FONT = packaged_font('Anton-Regular.ttf', 'Anton', 'Impact')
BODY_FONT = packaged_font('ChakraPetch-Regular.ttf', 'Chakra Petch', 'Bahnschrift')
packaged_font('ChakraPetch-SemiBold.ttf', 'Chakra Petch', BODY_FONT)


def motion_enabled():
    if os.name != 'nt':
        return True
    enabled = ctypes.c_int(1)
    ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    return bool(enabled.value)


MOTION = motion_enabled()


def blend(start, end, fraction):
    channels = (round(int(start[i:i+2], 16)*(1-fraction) + int(end[i:i+2], 16)*fraction)
                for i in (1, 3, 5))
    return '#{:02x}{:02x}{:02x}'.format(*channels)


ICONS = {
    'overview': ((2, 9, 10, 2, 18, 9), (4, 8, 4, 17, 16, 17, 16, 8), (8, 17, 8, 12, 12, 12, 12, 17)),
    'training': ((2, 10, 6, 10, 9, 3, 12, 16, 15, 10, 18, 10),),
    'maps': ((2, 5, 7, 3, 13, 5, 18, 3, 18, 15, 13, 17, 7, 15, 2, 17, 2, 5), (7, 3, 7, 15), (13, 5, 13, 17)),
    'alerts': ((3, 16, 3, 4, 17, 4), (6, 13, 9, 10, 12, 12, 17, 7), (3, 16, 17, 16)),
    'profile': ((6, 6, 8, 3, 12, 3, 14, 6, 12, 9, 8, 9, 6, 6), (3, 17, 4, 14, 7, 12, 13, 12, 16, 14, 17, 17)),
}


def draw_icon(canvas, icon, x, y, color):
    for path in ICONS[icon]:
        points = [offset + value for pair in zip(path[::2], path[1::2])
                  for offset, value in zip((x-10, y-10), pair)]
        canvas.create_line(*points, fill=color, width=1.6, capstyle='round', joinstyle='round')


def rounded(canvas, x1, y1, x2, y2, radius=14, **kwargs):
    radius = max(0, min(radius, (x2-x1)/2, (y2-y1)/2))
    points = [x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
              x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
              x1, y2, x1, y2-radius, x1, y1+radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class Surface(tk.Frame):
    def __init__(self, parent, color=PANEL, radius=18, padding=20, border=BORDER, **kwargs):
        super().__init__(parent, bg=parent.cget('bg'), **kwargs)
        self.color, self.radius, self.padding, self.border = color, radius, padding, border
        self.canvas = tk.Canvas(self, bg=self.cget('bg'), height=1, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.body = tk.Frame(self.canvas, bg=color)
        self.window = self.canvas.create_window(padding, padding, window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._measure)
        self.canvas.bind('<Configure>', self._resize)
        self.after_idle(self._measure)

    def _measure(self, event=None):
        requested = self.body.winfo_reqheight()+2*self.padding
        if int(float(self.canvas.cget('height'))) != requested:
            self.canvas.configure(height=requested)

    def _resize(self, event=None):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.canvas.delete('surface')
        rounded(self.canvas, 1, 1, width-1, height-1, self.radius,
                fill=self.color, outline=self.border, tags='surface')
        self.canvas.tag_lower('surface')
        self.canvas.itemconfigure(self.window, width=max(1, width-2*self.padding))


class Button(tk.Canvas):
    def __init__(self, parent, text='', command=None, textvariable=None,
                 kind='secondary', width=None, height=44, nav_icon=None, **kwargs):
        self.font = tkfont.Font(family=BODY_FONT, size=11, weight='bold')
        self.text, self.variable, self.command, self.kind = text, textvariable, command, kind
        self.state, self.hover, self.focused = 'normal', False, False
        self.hover_level, self.hover_timer = 0, None
        self.fixed_width, self.nav_icon = width, nav_icon
        self._trace = None
        super().__init__(parent, width=width or 160, height=height, bg=parent.cget('bg'),
                         bd=0, highlightthickness=0, takefocus=True, cursor='hand2', **kwargs)
        if self.variable is not None:
            self._trace = self.variable.trace_add('write', self._changed)
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda event: self._hover(True))
        self.bind('<Leave>', lambda event: self._hover(False))
        self.bind('<FocusIn>', lambda event: self._focus(True))
        self.bind('<FocusOut>', lambda event: self._focus(False))
        self.bind('<Button-1>', lambda event: self.invoke())
        self.bind('<Return>', self._key_invoke)
        self.bind('<space>', self._key_invoke)
        self.bind('<Destroy>', self._cleanup, add='+')
        self._changed()

    def _cleanup(self, event):
        if event.widget is not self:
            return
        if self.hover_timer is not None:
            self.after_cancel(self.hover_timer)
        if self.variable is not None and self._trace:
            self.variable.trace_remove('write', self._trace)
            self._trace = None

    def _changed(self, *args):
        text = self.variable.get() if self.variable is not None else self.text
        if self.fixed_width is None:
            super().configure(width=self.font.measure(text)+36)
        self._draw()

    def _hover(self, value):
        self.hover = value
        if self.hover_timer is not None:
            self.after_cancel(self.hover_timer)
        self._animate_hover()

    def _animate_hover(self):
        target = 6 if self.hover else 0
        if not MOTION:
            self.hover_level = target
        elif self.hover_level != target:
            self.hover_level += 1 if self.hover else -1
        self._draw()
        self.hover_timer = self.after(16, self._animate_hover) if self.hover_level != target else None

    def _focus(self, value):
        self.focused = value
        self._draw()

    def _draw(self, event=None):
        self.delete('all')
        disabled = self.state == 'disabled'
        if self.kind == 'primary':
            fill, highlight, foreground = VIOLET, LAVENDER, '#1a1227'
        elif self.kind == 'danger':
            fill, highlight, foreground = '#412638', '#602f47', RED
        elif self.kind == 'selected':
            fill, highlight, foreground = ACTIVE, '#483563', LAVENDER
        elif self.nav_icon:
            fill, highlight, foreground = RAIL, FIELD, MUTED
        else:
            fill, highlight, foreground = FIELD, '#44375c', TEXT
        fill = blend(fill, highlight, self.hover_level/6)
        if disabled:
            fill, foreground = '#231f32', '#a59ab9'
        width = self.winfo_width() if self.winfo_width() > 1 else int(self.cget('width'))
        height = self.winfo_height() if self.winfo_height() > 1 else int(self.cget('height'))
        rounded(self, 1, 1, width-1, height-1, 10, fill=fill,
                outline=VIOLET if self.focused and not disabled else fill, width=2)
        text = self.variable.get() if self.variable is not None else self.text
        if self.nav_icon:
            if self.kind == 'selected':
                rounded(self, 4, 10, 7, height-10, 2, fill=VIOLET, outline='')
            draw_icon(self, self.nav_icon, 23, height/2, foreground)
            self.create_text(43, height/2, text=text, fill=foreground, font=self.font, anchor='w')
        else:
            self.create_text(width/2, height/2, text=text, fill=foreground, font=self.font)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        if 'state' in kwargs:
            self.state = kwargs.pop('state')
            super().configure(takefocus=self.state != 'disabled', cursor='arrow' if self.state == 'disabled' else 'hand2')
        if 'text' in kwargs:
            self.text = kwargs.pop('text')
        if 'kind' in kwargs:
            self.kind = kwargs.pop('kind')
        if kwargs:
            super().configure(**kwargs)
        self._changed()

    config = configure

    def instate(self, states):
        return all((self.state == 'disabled') if state == 'disabled' else
                   (self.state != 'disabled') if state == '!disabled' else False for state in states)

    def invoke(self):
        if self.state != 'disabled' and self.command:
            self.focus_set()
            return self.command()

    def _key_invoke(self, event):
        self.invoke()
        return 'break'


class Check(tk.Canvas):
    def __init__(self, parent, text, variable, command=None):
        super().__init__(parent, bg=parent.cget('bg'), bd=0, highlightthickness=0,
                         height=38, takefocus=True, cursor='hand2')
        self.text, self.variable, self.command = text, variable, command
        self.font = tkfont.Font(family=BODY_FONT, size=10)
        self.focused = False
        self._trace = variable.trace_add('write', self._draw)
        self.bind('<Configure>', self._draw)
        self.bind('<Button-1>', self.toggle)
        self.bind('<space>', self.toggle)
        self.bind('<FocusIn>', lambda event: self._focus(True))
        self.bind('<FocusOut>', lambda event: self._focus(False))
        self.bind('<Destroy>', self._cleanup, add='+')

    def _cleanup(self, event):
        if event.widget is self and self._trace:
            self.variable.trace_remove('write', self._trace)
            self._trace = None

    def _focus(self, value):
        self.focused = value
        self._draw()

    def _draw(self, *args):
        self.delete('all')
        selected = self.variable.get()
        rounded(self, 2, 7, 24, 29, 6, fill=ACCENT if selected else FIELD,
                outline=ACCENT if selected or self.focused else '#7a91ac', width=2)
        if selected:
            self.create_line(7, 18, 12, 23, 20, 13, fill=BG, width=2.5, capstyle='round', joinstyle='round')
        item = self.create_text(36, 8, anchor='nw', text=self.text, fill=MUTED, font=self.font,
                                width=max(100, self.winfo_width()-44))
        bounds = self.bbox(item)
        height = max(38, bounds[3]+8) if bounds else 38
        if int(self.cget('height')) != height:
            self.configure(height=height)

    def toggle(self, event=None):
        self.focus_set()
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()
        return 'break'


class Progress(tk.Canvas):
    def __init__(self, parent, maximum=100, value=0):
        self.maximum, self.value = maximum, value
        super().__init__(parent, bg=parent.cget('bg'), height=12, bd=0, highlightthickness=0)
        self.bind('<Configure>', self._draw)

    def _draw(self, event=None):
        self.delete('all')
        width = max(1, self.winfo_width())
        rounded(self, 0, 0, width, 12, 6, fill=FIELD, outline='')
        filled = width*min(1, max(0, float(self.value)/max(1, float(self.maximum))))
        if filled > 0:
            rounded(self, 0, 0, filled, 12, 6, fill=blend(VIOLET, ACCENT, filled/width), outline='')

    def __getitem__(self, name):
        return getattr(self, name) if name in ('maximum', 'value') else super().__getitem__(name)

    def __setitem__(self, name, value):
        if name in ('maximum', 'value'):
            setattr(self, name, value)
            self._draw()
        else:
            super().__setitem__(name, value)


def field(parent, variable, kind='entry', **kwargs):
    """Rounded outline around a borderless native text, number or choice field."""
    shell = Surface(parent, color=FIELD, radius=11, padding=7, border=BORDER)
    if kind == 'combo':
        widget = ttk.Combobox(shell.body, textvariable=variable, font=(BODY_FONT, 11), **kwargs)
    elif kind == 'number':
        widget = ttk.Spinbox(shell.body, textvariable=variable, font=(BODY_FONT, 11), **kwargs)
    else:
        widget = tk.Entry(shell.body, textvariable=variable, bg=FIELD, fg=TEXT, insertbackground=ACCENT,
                          relief='flat', bd=0, highlightthickness=0, font=(BODY_FONT, 12), **kwargs)
    widget.pack(fill='x', expand=True)
    shell.canvas.configure(width=widget.winfo_reqwidth()+14, height=widget.winfo_reqheight()+14)
    widget.bind('<FocusIn>', lambda event: _field_focus(shell, True), add='+')
    widget.bind('<FocusOut>', lambda event: _field_focus(shell, False), add='+')
    return shell, widget


def _field_focus(shell, focused):
    shell.border = ACCENT if focused else BORDER
    shell._resize()


def configure(root):
    root.configure(bg=BG)
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
        tkfont.nametofont(name, root=root).configure(family=TITLE_FONT if name == 'TkHeadingFont' else BODY_FONT, size=11)
    style = ttk.Style(root)
    style.theme_use('clam')
    for name in ('TCombobox', 'TSpinbox'):
        style.configure(name, fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        arrowcolor=MUTED, padding=(4, 3), borderwidth=0, relief='flat')
        style.map(name, fieldbackground=[('readonly', FIELD), ('disabled', FIELD)],
                  foreground=[('disabled', '#8193aa'), ('readonly', TEXT)],
                  selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TEXT)],
                  bordercolor=[('focus', FIELD), ('!focus', FIELD)],
                  lightcolor=[('focus', FIELD), ('!focus', FIELD)], darkcolor=[('focus', FIELD), ('!focus', FIELD)])
    style.configure('Enroll.Horizontal.TProgressbar', background=VIOLET, troughcolor=FIELD,
                    borderwidth=0, thickness=8)
    style.configure('Page.Vertical.TScrollbar', background=FIELD, troughcolor=BG,
                    arrowcolor=MUTED, borderwidth=0, arrowsize=12)
    root.option_add('*TCombobox*Listbox.font', (BODY_FONT, 11))
    root.option_add('*TCombobox*Listbox.background', FIELD)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', ACTIVE)
