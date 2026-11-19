"""Readable pages for protection, training, mouse maps and recent alerts."""
import math
import time
import tkinter as tk
from tkinter import ttk
from branding import load_logo, set_icon
from heatmap import HeatField, heat_rgb, raster_ppm
from metrics import TYPING_PAUSE_SECONDS
from ui_theme import (
    BG, RAIL, PANEL, FIELD, BORDER, TEXT, MUTED, ACCENT, AMBER, RED, HERO,
    VIOLET, LAVENDER, BLUE, TILE, BODY_FONT, TITLE_FONT, MOTION,
    Surface, Button, Check, Progress, field, configure, rounded,
)

PAGES = {
    'overview': ('Overview', 'Start protection and see your current activity.'),
    'training': ('Training', 'Teach the app your usual typing and mouse habits.'),
    'maps': ('Mouse maps', 'Compare your saved mouse pattern with current activity.'),
    'alerts': ('Alerts & history', 'See why an alert appeared and review recent activity.'),
    'profile': ('Profile', 'Manage the selected profile and its saved behavior.'),
}


def label(parent, text='', size=11, color=TEXT, bold=False, title=False, **kwargs):
    font = (TITLE_FONT, size) if title else (BODY_FONT, size, 'bold' if bold else 'normal')
    return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                    font=font, **kwargs)


def paragraph(parent, text='', variable=None, color=MUTED, size=11, pady=(6, 0)):
    widget = label(parent, text, size, color, textvariable=variable, justify='left', anchor='w', wraplength=300)
    widget.pack(fill='x', pady=pady)
    parent.bind('<Configure>', lambda event: widget.configure(wraplength=max(100, event.width-4)), add='+')
    return widget


def card(parent, *, grid=None, padding=20, color=PANEL, border=BORDER, **pack):
    surface = Surface(parent, padding=padding, color=color, border=border, radius=18)
    if grid is not None:
        surface.grid(**grid)
    else:
        surface.pack(fill='x', **pack)
    return surface.body


def heading(parent, title, detail=None):
    label(parent, title, 16, title=True, anchor='w').pack(fill='x')
    if detail:
        paragraph(parent, detail)


class ShieldSignal(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=208, height=185, bg=HERO, highlightthickness=0)
        self.shield = load_logo(self, 67)
        self.timer = None
        self.sweep = None
        self.bind('<Configure>', self.draw)
        self.bind('<Map>', self.resume)
        self.bind('<Unmap>', self.stop)
        self.bind('<Destroy>', self.stop)

    def draw(self, event):
        self.delete('all')
        self.x, self.y = event.width/2, event.height/2
        self.radius = min(75, self.x-12, self.y-12)
        if self.radius < 20:
            self.sweep = None
            return
        x, y, r = self.x, self.y, self.radius
        rounded(self, x-r-10, y-r-10, x+r+10, y+r+10, 23, fill='#2e2348', outline='#41305e')
        for shift in (-.6, -.3, 0, .3, .6):
            self.create_line(x-r, y+r*shift, x+r, y+r*shift, fill='#3a2c53')
            self.create_line(x+r*shift, y-r, x+r*shift, y+r, fill='#3a2c53')
        for scale in (.45, .72, 1):
            radius = r*scale
            self.create_oval(x-radius, y-radius, x+radius, y+radius, outline='#614985')
        self.sweep = self.create_arc(x-r, y-r, x+r, y+r, extent=73, style='arc', outline=VIOLET, width=3)
        self.point = self.create_oval(0, 0, 0, 0, fill=ACCENT, outline='')
        self.create_line(x-r*.78, y+r*.40, x-r*.4, y+r*.40, x-r*.19, y+r*.20, x+r*.03, y+r*.54,
                         x+r*.28, y+r*.33, x+r*.47, y+r*.33, fill='#8263b4', width=2, joinstyle='round')
        if self.shield is not None:
            self.create_image(x, y-5, image=self.shield)
        self.paint()

    def paint(self):
        if self.sweep is None:
            return
        angle = (time.monotonic()*46) % 360 if MOTION else 23
        self.itemconfigure(self.sweep, start=angle)
        radians = math.radians(angle+73)
        x = self.x+self.radius*math.cos(radians)
        y = self.y-self.radius*math.sin(radians)
        self.coords(self.point, x-3, y-3, x+3, y+3)

    def resume(self, event=None):
        if MOTION and self.timer is None:
            self.paint()
            self.timer = self.after(42, self.next_frame)

    def next_frame(self):
        self.timer = None
        if self.winfo_ismapped():
            self.resume()

    def stop(self, event=None):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None


def stop_page_accent(app):
    if app.page_animation is not None:
        app.page_accent.after_cancel(app.page_animation)
        app.page_animation = None


def show_page_accent(app):
    bar = app.page_accent
    stop_page_accent(app)

    def frame(step):
        width = int(68*(1-(1-step/10)**3))
        bar.coords('accent', 0, 0, width, 3)
        app.page_animation = bar.after(16, frame, step+1) if step < 10 else None

    frame(1 if MOTION else 10)


def show_page(app, name):
    if name not in app.pages:
        return
    for key, page in app.pages.items():
        if key != name:
            page.pack_forget()
    if not app.pages[name].winfo_manager():
        app.pages[name].pack(fill='both', expand=True)
    app.current_page = name
    app.page_title.set(PAGES[name][0])
    app.page_subtitle.set(PAGES[name][1])
    for key, button in app.nav_buttons.items():
        button.configure(kind='selected' if key == name else 'secondary')
    app.page_canvas.yview_moveto(0)
    show_page_accent(app)
    app.root.update_idletasks()
    if name == 'maps':
        app.draw_heatmap()
    elif name == 'alerts':
        app.draw(app.thresholds[app.sensitivity.get()])


def refresh(app):
    ready, busy = app.ai is not None and app.mode != 'train', app.future is not None
    app.profile_summary.set('No profile selected' if not app.profile else
                            'Ready for protection' if ready else 'Training needed')
    app.training_start_button.configure(state='disabled' if busy or app.active else 'normal')
    for button in app.pause_buttons:
        button.configure(state='normal' if app.active else 'disabled')
    app.delete_button.configure(state='normal' if app.profile else 'disabled')
    if app.mode == 'monitor':
        app.training_controls.pack_forget()
        if not app.training_ready.winfo_manager():
            app.training_ready.pack(fill='x', before=app.practice_panel, pady=(0, 18))
    else:
        app.training_ready.pack_forget()
        if not app.training_controls.winfo_manager():
            app.training_controls.pack(fill='x', before=app.practice_panel, pady=(0, 18))
    delay = {'Low': 2.5, 'Balanced': 5, 'High': 7.5}[app.sensitivity.get()]
    app.mode_help.set(f'Timed alerts wait {delay:g} seconds. Mouse speed and long key holds are checked immediately.')
    pause_mouse = app.pause_mouse_while_typing.get()
    app.both_inputs_button.configure(kind='secondary' if pause_mouse else 'selected')
    app.typing_first_button.configure(kind='selected' if pause_mouse else 'secondary')
    app.mouse_mode_help.set(f'Mouse alerts pause while typing and resume after {TYPING_PAUSE_SECONDS:g}s without typing.'
                            if pause_mouse else 'Typing and mouse checks stay on together.')
    app.mouse_check_status.set('Mouse checks paused while typing.' if app.active and pause_mouse and app.mouse_was_paused else
                              'Mouse checks running.' if app.active and app.mode == 'monitor' else 'Mouse checks start with protection.')
    if not app.profile:
        next_step = 'Create a profile, then open Training to get started.'
    elif busy:
        next_step = 'Preparing your saved behavior. Please wait.'
    elif app.active:
        next_step = 'You can use your other apps. Pause whenever you want to stop tracking.'
    elif ready:
        next_step = 'Allow tracking below, then choose Start protection.'
    else:
        next_step = 'Open Training, choose a duration, and start a session.'
    app.next_step.set(next_step)
    app.state_dot.delete('all')
    state_color = RED if app.risk_text.get() == 'Error' else ACCENT if app.active else AMBER
    app.state_dot.create_oval(3, 3, 13, 13, fill=state_color, outline='')


def build(app):
    root = app.root
    configure(root)
    set_icon(root)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    width, height = min(1220, sw-60), min(820, sh-90)
    root.geometry(f'{width}x{height}+{max(0, (sw-width)//2)}+{max(0, (sh-height)//2-15)}')
    root.minsize(min(940, sw-40), min(620, sh-80))
    defaults = {
        'status': 'Choose a profile to begin.', 'progress': '',
        'metric': 'Typing changes will appear here during protection.', 'sensitivity': 'Balanced',
        'profile_name': 'Choose a profile', 'baseline_text': '', 'duration_value': '5',
        'duration_unit': 'minutes', 'start_text': 'Start training', 'risk_text': 'Paused',
        'keyboard_text': 'Training needed', 'mouse_text': 'Training needed',
        'speed_text': '—', 'dwell_text': '—', 'edge_text': '—', 'edge_detail': 'No activity yet',
        'heatmap_detail': '', 'last_alert_text': 'No alerts for this profile.',
        'recorded_detail': '', 'current_detail': '', 'area_info': '',
        'profile_summary': '', 'mode_help': '', 'next_step': '',
        'typing_speed_text': '0.0 keys/s', 'typing_reference_text': '',
        'mouse_mode_help': '', 'mouse_check_status': '',
        'phone_status': 'Phone alerts are off.',
        'page_title': 'Overview', 'page_subtitle': PAGES['overview'][1],
    }
    for name, value in defaults.items():
        setattr(app, name, tk.StringVar(root, value=value))
    app.consent = tk.BooleanVar(root)
    app.pause_mouse_while_typing = tk.BooleanVar(root, value=True)
    app.map_images, app.pages, app.nav_buttons = {}, {}, {}
    app.pause_buttons, app.current_page = [], 'overview'
    app.show_page = lambda name: show_page(app, name)
    shell = tk.Frame(root, bg=BG)
    shell.pack(fill='both', expand=True)
    rail = tk.Frame(shell, bg=RAIL, width=204, highlightbackground=BORDER, highlightthickness=1)
    rail.pack(side='left', fill='y')
    rail.pack_propagate(False)
    brand = tk.Frame(rail, bg=RAIL)
    brand.pack(fill='x', padx=18, pady=(28, 26))
    app.logo = load_logo(root, 38)
    if app.logo is not None:
        tk.Label(brand, image=app.logo, bg=RAIL).pack(side='left', padx=(0, 12))
    label(brand, 'Behavioral\nGuard', 16, color=LAVENDER, title=True, justify='left').pack(side='left')
    tk.Frame(rail, bg=BORDER, height=1).pack(fill='x', padx=16, pady=(0, 16))
    for name, (title, _) in PAGES.items():
        button = Button(rail, title, command=lambda key=name: app.show_page(key), nav_icon=name)
        button.pack(fill='x', padx=12, pady=3)
        app.nav_buttons[name] = button
    footer = tk.Frame(rail, bg=RAIL)
    footer.pack(side='bottom', fill='x', padx=14, pady=18)
    tk.Frame(footer, bg=BORDER, height=1).pack(fill='x', pady=(0, 14))
    label(footer, 'Your profile', 11, MUTED, True).pack(anchor='w', pady=(0, 6))
    selector, app.profile_selector = field(footer, app.profile_name, kind='combo', state='readonly', width=12)
    selector.pack(fill='x')
    app.profile_selector.bind('<<ComboboxSelected>>', app.switch_profile)
    Button(footer, 'New profile', command=app.new_profile).pack(fill='x', pady=(8, 0))
    workspace = tk.Frame(shell, bg=BG)
    workspace.pack(side='left', fill='both', expand=True)
    header = tk.Frame(workspace, bg=BG)
    header.pack(fill='x', padx=26, pady=(23, 16))
    title_row = tk.Frame(header, bg=BG)
    title_row.pack(fill='x')
    label(title_row, textvariable=app.page_title, size=31, title=True).pack(side='left')
    global_pause = Button(title_row, 'Pause', command=app.pause, width=104, height=40)
    global_pause.pack(side='right')
    app.pause_buttons.append(global_pause)
    paragraph(header, variable=app.page_subtitle, pady=(4, 12))
    app.page_animation = None
    app.page_accent = tk.Canvas(header, bg=BORDER, height=3, highlightthickness=0, bd=0)
    app.page_accent.create_rectangle(0, 0, 68, 3, fill=VIOLET, outline='', tags='accent')
    app.page_accent.pack(fill='x')
    app.page_accent.bind('<Destroy>', lambda event: stop_page_accent(app))
    viewport = tk.Frame(workspace, bg=BG)
    viewport.pack(fill='both', expand=True)
    app.page_canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0, bd=0)
    scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=app.page_canvas.yview, style='Page.Vertical.TScrollbar')
    scrollbar.pack(side='right', fill='y')
    app.page_canvas.pack(side='left', fill='both', expand=True)
    app.page_canvas.configure(yscrollcommand=scrollbar.set)
    padding = tk.Frame(app.page_canvas, bg=BG)
    window = app.page_canvas.create_window(0, 0, window=padding, anchor='nw')
    padding.bind('<Configure>', lambda event: app.page_canvas.configure(scrollregion=app.page_canvas.bbox('all')))
    app.page_canvas.bind('<Configure>', lambda event: app.page_canvas.itemconfigure(window, width=event.width))
    for name in PAGES:
        app.pages[name] = tk.Frame(padding, bg=BG, padx=26, pady=2)
    def scroll_page(event):
        if not isinstance(event.widget, (tk.Text, ttk.Combobox, ttk.Spinbox)) and app.page_canvas.yview() != (0.0, 1.0):
            app.page_canvas.yview_scroll(-int(event.delta/120), 'units')
    root.bind('<MouseWheel>', scroll_page, add='+')

    overview = app.pages['overview']
    hero = card(overview, pady=(0, 20), padding=20, color=HERO, border='#594175')
    ShieldSignal(hero).pack(side='right', fill='y', padx=(14, 0))
    hero_copy = tk.Frame(hero, bg=HERO)
    hero_copy.pack(side='left', fill='both', expand=True)
    state = tk.Frame(hero_copy, bg=HERO)
    state.pack(fill='x')
    app.state_dot = tk.Canvas(state, width=17, height=17, bg=HERO, highlightthickness=0)
    app.state_dot.pack(side='left', padx=(0, 8))
    label(state, 'Protection status', 11, LAVENDER, True).pack(side='left')
    risk = label(hero_copy, textvariable=app.risk_text, size=37, title=True)
    risk.pack(anchor='w', pady=(2, 0))
    app.risk_text.trace_add('write', lambda *_: risk.configure(fg=RED if app.risk_text.get() == 'Error' else TEXT))
    paragraph(hero_copy, variable=app.status, color=LAVENDER, pady=(2, 0))
    paragraph(hero_copy, variable=app.next_step, pady=(5, 12))
    controls = tk.Frame(hero_copy, bg=HERO)
    controls.pack(fill='x')
    app.start_button = Button(controls, textvariable=app.start_text, kind='primary',
                              command=lambda: app.show_page('training') if app.mode == 'train' else app.start())
    app.start_button.pack(side='left')
    Check(hero_copy, 'Allow typing and mouse tracking while this app is running.', app.consent,
          command=lambda: None if app.consent.get() else app.pause()).pack(fill='x', pady=(12, 0))
    label(overview, 'Live activity', 19, title=True).pack(anchor='w', pady=(0, 9))
    metrics = tk.Frame(overview, bg=BG)
    metrics.pack(fill='x', pady=(0, 18))
    metric_cards = []
    for title, value, detail, tone, surface_color in (
        ('Typing speed', app.typing_speed_text, 'Key presses per second', ACCENT, '#192c35'),
        ('Mouse speed', app.speed_text, 'Average while moving', BLUE, '#232c45'),
        ('Key hold time', app.dwell_text, 'Time a key stays pressed', VIOLET, '#2b2341'),
        ('Screen edge time', app.edge_text, 'Recent time near an edge', AMBER, '#342838'),
    ):
        tile = Surface(metrics, color=surface_color, border=BORDER, radius=15, padding=14)
        metric_cards.append(tile)
        body = tile.body
        top = tk.Frame(body, bg=surface_color)
        top.pack(fill='x')
        tk.Frame(top, width=4, height=14, bg=tone).pack(side='left', padx=(0, 8))
        label(top, title, 11, TEXT, True).pack(side='left')
        label(body, textvariable=value, size=21, color=tone, title=True).pack(anchor='w', pady=(4, 0))
        paragraph(body, detail, size=10, pady=(2, 0))

    columns = None

    def lay_out_metrics(event=None):
        nonlocal columns
        count = 4 if event is not None and event.width >= 810 else 2
        if columns == count:
            return
        columns = count
        for index in range(4):
            metrics.columnconfigure(index, weight=int(index < count), uniform='metrics' if index < count else '')
        for index, tile in enumerate(metric_cards):
            column = index % count
            tile.grid(row=index//count, column=column, sticky='nsew',
                      padx=(0 if column == 0 else 5, 0 if column == count-1 else 5), pady=(0, 10))

    lay_out_metrics()
    metrics.bind('<Configure>', lay_out_metrics)
    input_mode = card(overview, pady=(0, 18), border='#48405f')
    heading(input_mode, 'Mouse checks while typing')
    mode_buttons = tk.Frame(input_mode, bg=PANEL)
    mode_buttons.pack(fill='x', pady=(14, 0))
    app.both_inputs_button = Button(mode_buttons, 'Check both', command=lambda: app.set_mouse_mode(False), width=140)
    app.both_inputs_button.pack(side='left')
    app.typing_first_button = Button(mode_buttons, 'Pause mouse while typing', command=lambda: app.set_mouse_mode(True), width=250)
    app.typing_first_button.pack(side='left', padx=(10, 0))
    paragraph(input_mode, variable=app.mouse_mode_help, size=10, pady=(12, 0))
    paragraph(input_mode, variable=app.mouse_check_status, color=ACCENT, size=10)
    summary = tk.Frame(overview, bg=BG)
    summary.pack(fill='x', pady=(0, 18))
    summary.columnconfigure((0, 1), weight=1, uniform='summary')
    ready = card(summary, grid={'row': 0, 'column': 0, 'sticky': 'nsew', 'padx': (0, 7)})
    heading(ready, 'Saved behavior')
    paragraph(ready, variable=app.profile_summary, color=ACCENT, pady=(8, 12))
    for title, variable in (('Typing', app.keyboard_text), ('Mouse', app.mouse_text)):
        row = tk.Frame(ready, bg=PANEL)
        row.pack(fill='x', pady=4)
        label(row, title, 11, MUTED).pack(side='left')
        label(row, textvariable=variable, size=11, bold=True).pack(side='right')
    Button(ready, 'Open training', command=lambda: app.show_page('training')).pack(anchor='w', pady=(14, 0))
    timing = card(summary, grid={'row': 0, 'column': 1, 'sticky': 'nsew', 'padx': (7, 0)})
    heading(timing, 'Alert timing')
    mode, app.mode_selector = field(timing, app.sensitivity, kind='combo', state='readonly', values=list(app.thresholds), width=13)
    mode.pack(fill='x', pady=(12, 0))
    paragraph(timing, variable=app.mode_help, size=10, pady=(12, 0))
    recent = card(overview, pady=(0, 24))
    heading(recent, 'Latest alert')
    paragraph(recent, variable=app.last_alert_text)
    Button(recent, 'View alert history', command=lambda: app.show_page('alerts')).pack(anchor='w', pady=(14, 0))

    training = app.pages['training']
    guide = card(training, pady=(0, 18))
    heading(guide, 'How training works')
    for text in ('1. Choose how long to record your usual behavior.',
                 '2. Start training, then type and move your mouse normally.',
                 '3. Protection starts when training is complete.'):
        paragraph(guide, text, pady=(8, 0))
    app.training_controls = Surface(training, padding=22)
    session = app.training_controls.body
    heading(session, 'Training session', 'You can use this app or any of your other apps.')
    label(session, 'Duration', 11, bold=True).pack(anchor='w', pady=(16, 6))
    duration = tk.Frame(session, bg=PANEL)
    duration.pack(fill='x')
    number, app.duration_input = field(duration, app.duration_value, kind='number', from_=1, to=3600, increment=1, width=7)
    number.pack(side='left')
    unit, app.unit_selector = field(duration, app.duration_unit, kind='combo', state='readonly', values=['minutes', 'seconds'], width=10)
    unit.pack(side='left', padx=(10, 0))
    paragraph(session, 'Choose 10 seconds to 60 minutes.', size=10)
    progress_row = tk.Frame(session, bg=PANEL)
    progress_row.pack(fill='x', pady=(18, 8))
    label(progress_row, 'Time remaining', 10, MUTED).pack(side='left')
    label(progress_row, textvariable=app.progress, size=12, color=ACCENT, bold=True).pack(side='right')
    app.training_bar = Progress(session, maximum=300)
    app.training_bar.pack(fill='x', pady=(0, 16))
    session_actions = tk.Frame(session, bg=PANEL)
    session_actions.pack(fill='x')
    app.training_start_button = Button(session_actions, textvariable=app.start_text, command=app.start, kind='primary')
    app.training_start_button.pack(side='left')
    pause_training = Button(session_actions, 'Pause', command=app.pause, width=100)
    pause_training.pack(side='left', padx=10)
    app.pause_buttons.append(pause_training)
    Check(session, 'Allow typing and mouse tracking while this app is running.', app.consent,
          command=lambda: None if app.consent.get() else app.pause()).pack(fill='x', pady=(12, 0))
    app.training_ready = Surface(training, padding=22)
    heading(app.training_ready.body, 'Your profile is trained')
    paragraph(app.training_ready.body, 'Add another session to teach the app more of your usual behavior. Your saved training is kept.')
    app.learn_button = Button(app.training_ready.body, 'Add training', command=app.learn_more, kind='primary')
    app.learn_button.pack(anchor='w', pady=(16, 0))
    app.practice_panel = Surface(training)
    app.practice_panel.pack(fill='x', pady=(0, 24))
    practice = app.practice_panel.body
    heading(practice, 'Optional typing area', 'Type here during training or protection. This text is cleared when you pause.')
    label(practice, 'Current typing speed', 10, MUTED).pack(anchor='w', pady=(12, 0))
    paragraph(practice, variable=app.typing_speed_text, color=ACCENT, size=12, pady=(3, 0))
    typing_surface = Surface(practice, color=FIELD, radius=12, padding=10, border=FIELD)
    typing_surface.pack(fill='x', pady=(14, 0))
    app.practice = tk.Text(typing_surface.body, height=5, bg=FIELD, fg=TEXT, insertbackground=ACCENT,
                           bd=0, highlightthickness=0, font=(BODY_FONT, 11), wrap='word', undo=False)
    app.practice.pack(fill='both', expand=True)

    maps = app.pages['maps']
    explanation = card(maps, pady=(0, 18))
    heading(explanation, 'Saved pattern and current activity')
    paragraph(explanation, 'The saved map changes only during training or after you approve new behavior. Current activity is saved separately.')
    map_grid = tk.Frame(maps, bg=BG)
    map_grid.pack(fill='x')
    map_grid.columnconfigure((0, 1), weight=1, uniform='maps')
    for col, (title, variable, detail, attribute) in enumerate((
        ('Saved pattern', app.recorded_detail, 'Your approved mouse behavior', 'recorded_canvas'),
        ('Current activity', app.current_detail, 'Mouse use during protection', 'current_canvas'))):
        body = card(map_grid, grid={'row': 0, 'column': col, 'sticky': 'nsew', 'padx': (0, 7) if col == 0 else (7, 0)}, padding=16)
        heading(body, title)
        paragraph(body, detail, size=10, pady=(4, 0))
        canvas = tk.Canvas(body, height=260, bg=PANEL, highlightthickness=0, bd=0)
        canvas.pack(fill='x', pady=(12, 4))
        setattr(app, attribute, canvas)
        paragraph(body, variable=variable, size=10)
    app.heatmap_canvas = app.current_canvas
    legend = card(maps, pady=(18, 24))
    heading(legend, 'Reading the colors')
    scale = tk.Frame(legend, bg=PANEL)
    scale.pack(fill='x', pady=(12, 8))
    label(scale, 'Less time', 10, MUTED).pack(side='left', padx=(0, 10))
    for fraction in (0, .2, .4, .6, .8, 1):
        tk.Label(scale, bg=heat_color(fraction), width=3, height=1).pack(side='left')
    label(scale, 'More time', 10, MUTED).pack(side='left', padx=10)
    paragraph(legend, 'Orange areas allow more time without moving. Empty areas use the selected alert timing.', size=10)
    paragraph(legend, variable=app.area_info, color=ACCENT, size=10, pady=(10, 0))
    Button(legend, 'Clear current activity', command=app.reset_heatmap).pack(anchor='w', pady=(16, 0))

    alerts = app.pages['alerts']
    latest = card(alerts, pady=(0, 18))
    heading(latest, 'Latest alert')
    paragraph(latest, variable=app.last_alert_text, color=AMBER, pady=(12, 0))
    graph = card(alerts, pady=(0, 18))
    heading(graph, 'Typing speed & rhythm', 'A higher line means your typing differs more from your saved pattern.')
    live_typing = tk.Frame(graph, bg=PANEL)
    live_typing.pack(fill='x', pady=(14, 0))
    label(live_typing, 'Current speed', 10, MUTED).pack(side='left', padx=(0, 10))
    label(live_typing, textvariable=app.typing_speed_text, size=14, color=ACCENT, bold=True).pack(side='left')
    paragraph(graph, variable=app.typing_reference_text, size=10)
    key = tk.Frame(graph, bg=PANEL)
    key.pack(fill='x', pady=(12, 0))
    label(key, 'Blue · Typing speed', 10, BLUE).pack(side='left', padx=(0, 22))
    label(key, 'Mint · Typing rhythm', 10, ACCENT).pack(side='left')
    app.chart = tk.Canvas(graph, height=180, bg=PANEL, highlightthickness=0, bd=0)
    app.chart.pack(fill='x', pady=(12, 0))
    paragraph(graph, variable=app.metric, size=10)
    events = card(alerts, pady=(0, 24))
    heading(events, 'Recent activity')
    log_area = tk.Frame(events, bg=PANEL)
    log_area.pack(fill='x', pady=(12, 0))
    app.log = tk.Text(log_area, height=9, bg=PANEL, fg=MUTED, bd=0, highlightthickness=0,
                      font=(BODY_FONT, 10), state='disabled', wrap='word', spacing3=8)
    log_scroll = ttk.Scrollbar(log_area, orient='vertical', command=app.log.yview, style='Page.Vertical.TScrollbar')
    log_scroll.pack(side='right', fill='y')
    app.log.pack(side='left', fill='both', expand=True)
    app.log.configure(yscrollcommand=log_scroll.set)

    profile = app.pages['profile']
    details = card(profile, pady=(0, 18))
    heading(details, 'Selected profile')
    profile_title = paragraph(details, variable=app.profile_name, size=22, color=TEXT, pady=(12, 2))
    profile_title.configure(font=(TITLE_FONT, 22))
    paragraph(details, variable=app.profile_summary, color=ACCENT)
    paragraph(details, 'Each profile has its own password, training, mouse maps and alert settings.', pady=(14, 0))
    Button(details, 'Create a new profile', command=app.new_profile).pack(anchor='w', pady=(16, 0))
    phone = card(profile, pady=(0, 18))
    heading(phone, 'Phone alerts', 'Receive alerts and answer Yes or No on your phone. Use the same Wi-Fi as this PC.')
    paragraph(phone, variable=app.phone_status, color=ACCENT, pady=(12, 0))
    pairing = tk.Frame(phone, bg=PANEL)
    pairing.pack(fill='x', pady=(16, 0))
    Button(pairing, 'Pair phone', command=app.pair_phone, kind='primary').pack(side='left')
    app.phone_test_button = Button(pairing, 'Test alert', command=app.test_phone)
    app.phone_test_button.pack(side='left', padx=10)
    app.phone_stop_button = Button(phone, 'Turn off phone alerts', command=app.stop_phone)
    app.phone_stop_button.pack(anchor='w', pady=(10, 0))
    privacy = card(profile, pady=(0, 18))
    heading(privacy, 'What is saved')
    paragraph(privacy, 'Typing times, mouse activity and approved behavior are saved on this PC. Your typed text is not saved.')
    remove = card(profile, pady=(0, 24))
    heading(remove, 'Delete this profile')
    paragraph(remove, 'This removes the selected profile and its saved behavior. You will be asked for its password.')
    app.delete_button = Button(remove, 'Delete profile', command=app.delete, kind='danger')
    app.delete_button.pack(anchor='w', pady=(16, 0))
    app.chart.bind('<Configure>', lambda event: app.draw(app.thresholds[app.sensitivity.get()]))
    app.current_canvas.bind('<Configure>', lambda event: app.draw_heatmap())
    app.recorded_canvas.bind('<Configure>', lambda event: app.draw_heatmap())
    app.sensitivity.trace_add('write', app.mode_changed)
    app.duration_value.trace_add('write', lambda *args: app.update_progress())
    app.duration_unit.trace_add('write', lambda *args: app.update_progress())
    app.show_page('overview')


def heat_color(fraction):
    return '#'+''.join(f'{value:02x}' for value in heat_rgb(fraction))


def draw_heatmap(app):
    recorded, current = app.recorded_heatmap(), app.collector.current_heatmap
    app.recorded_detail.set(f'{recorded.seconds/60:.1f} minutes saved')
    app.current_detail.set(f'{current.seconds/60:.1f} minutes saved')
    if app.current_page != 'maps':
        return
    paint_map(app, app.recorded_canvas, recorded, app.recorded_field(), 'recorded')
    paint_map(app, app.current_canvas, current, None, 'current')


def paint_map(app, canvas, heatmap, field, slot):
    canvas.delete('all')
    left, top, right, bottom = heatmap.layout.bounds
    width, height = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 130)
    scale = min((width-20)/(right-left), (height-20)/(bottom-top))
    rw, rh = max(1, int((right-left)*scale)//2), max(1, int((bottom-top)*scale)//2)
    offset_x, offset_y = (width-rw*2)/2, (height-rh*2)/2
    x, y = lambda value: offset_x+(value-left)*scale, lambda value: offset_y+(value-top)*scale
    stamp = (app.profile_id, heatmap.layout.identifier, heatmap.samples, heatmap.seconds, rw, rh)
    cache = app.map_images.get(slot)
    if cache is None or cache[0] != stamp:
        field = field or HeatField(heatmap)
        picture = tk.PhotoImage(master=canvas, data=raster_ppm(field, rw, rh), format='PPM').zoom(2)
        app.map_images[slot] = (stamp, picture)
    canvas.create_image(offset_x, offset_y, image=app.map_images[slot][1], anchor='nw')
    for index, (ml, mt, mr, mb) in enumerate(heatmap.layout.monitors, 1):
        canvas.create_rectangle(x(ml), y(mt), x(mr), y(mb), outline='#6e849f')
        canvas.create_text(x(ml)+7, y(mt)+7, text=f'Display {index}', anchor='nw', fill=TEXT, font=(BODY_FONT, 9))
    if not heatmap.samples:
        canvas.create_text(width/2, height/2, text='No saved pattern yet.\nStart a training session.' if slot == 'recorded'
                           else 'No activity yet.\nStart protection to record this map.',
                           fill=MUTED, font=(BODY_FONT, 10), width=width-32, justify='center')
    if slot == 'current' and app.collector.current_position is not None:
        px, py = app.collector.current_position
        canvas.create_oval(x(px)-3, y(py)-3, x(px)+3, y(py)+3, outline='white', width=2)


def draw_signal(app, threshold):
    canvas = app.chart
    canvas.delete('all')
    width, height = max(280, canvas.winfo_width()), max(130, canvas.winfo_height())
    left, right = 36, width-90
    y = lambda value: height-28-value*(height-50)
    for value in (0, .5, 1):
        canvas.create_line(left, y(value), right, y(value), fill=BORDER)
    canvas.create_line(left, y(threshold), right, y(threshold), fill=AMBER, dash=(5, 5))
    canvas.create_text(right+8, y(threshold), text='Alert level', anchor='w', fill=AMBER, font=(BODY_FONT, 9))
    history = app.typing_history or [(value, None) for value in app.history]
    for column, color, tag in ((0, ACCENT, 'typing_rhythm'), (1, BLUE, 'typing_speed')):
        segment = []
        def paint_segment():
            if len(segment) > 1:
                canvas.create_line(*[coordinate for point in segment for coordinate in point],
                                   fill=color, width=2, tags=tag)
            elif segment:
                px, py = segment[0]
                canvas.create_oval(px-2, py-2, px+2, py+2, fill=color, outline='', tags=tag)
        for index, values in enumerate(history):
            if values[column] is None:
                paint_segment()
                segment = []
            else:
                segment.append((left+index*(right-left)/119, y(values[column])))
        paint_segment()
    if not history:
        canvas.create_text(width/2, height/2, text='Typing activity will appear here during protection.',
                           fill=MUTED, font=(BODY_FONT, 11), width=width-60)
    canvas.create_text(left, height-8, anchor='w', text='Earlier', fill=MUTED, font=(BODY_FONT, 9))
    canvas.create_text(right, height-8, anchor='e', text='Now', fill=MUTED, font=(BODY_FONT, 9))
