"""Phone pairing and identity responses on Tk's main thread."""
import base64
import io
import tkinter as tk
from dialogs import Dialog
from ui_theme import BG, PANEL, TEXT, MUTED, ACCENT, RED, TITLE_FONT, BODY_FONT, Surface, Button, field


def ask_with_phone(parent, bridge, description, profile_name='', kind='behavior'):
    identifier = bridge.publish(description, profile_name, kind)
    is_test = kind == 'test'
    dialog = Dialog(parent, 'Test approval' if is_test else 'Is this you?', description,
                    question=True, desktop_alert=True, code=bridge.approval_code(identifier), test=is_test)
    timer = None

    def check():
        nonlocal timer
        if not dialog.winfo_exists():
            return
        answer = bridge.result(identifier)
        if answer is not None:
            dialog.result = answer
            dialog._finish()
        elif bridge.approval_code(identifier) is None:
            if dialog.code_panel is not None:
                dialog.code_panel.pack_forget()
            dialog.message_label.configure(text=description+'\n\nPhone request expired. Please answer on this PC.')
        else:
            timer = dialog.after(200, check)

    timer = dialog.after(200, check)
    try:
        answer = dialog.show()
    finally:
        if timer:
            try:
                parent.after_cancel(timer)
            except tk.TclError:
                pass
    return bridge.finish(identifier, answer), bridge.result_source(identifier)


class PairingWindow(tk.Toplevel):
    def __init__(self, parent, bridge):
        super().__init__(parent)
        self.title('Pair your phone')
        self.configure(bg=BG)
        self.transient(parent)
        self.resizable(False, False)
        self.bridge = bridge
        self.timer = None
        self.protocol('WM_DELETE_WINDOW', self.close)
        surface = Surface(self, padding=22)
        surface.pack(fill='both', expand=True, padx=12, pady=12)
        body = surface.body
        tk.Label(body, text='Pair your phone', bg=PANEL, fg=TEXT,
                 font=(TITLE_FONT, 22)).pack(anchor='w')
        tk.Label(body, text='Open Behavioral Guard on your phone and scan this code.\nUse the same Wi-Fi as this PC.',
                 bg=PANEL, fg=MUTED, wraplength=445, justify='left', font=(BODY_FONT, 11)).pack(fill='x', pady=(10, 14))
        tk.Label(body, text='PC address', bg=PANEL, fg=MUTED, font=(BODY_FONT, 10)).pack(anchor='w')
        self.address = tk.StringVar(value=bridge.addresses()[0])
        shell, selector = field(body, self.address, kind='combo', state='readonly', values=bridge.addresses())
        shell.pack(fill='x', pady=(6, 8))
        selector.bind('<<ComboboxSelected>>', self.refresh_code)
        self.image = tk.Label(body, bg=PANEL)
        self.image.pack(pady=(4, 8))
        self.note = tk.StringVar(value='This code expires in 10 minutes.')
        self.note_label = tk.Label(body, textvariable=self.note, bg=PANEL, fg=ACCENT, wraplength=445,
                                   justify='left', font=(BODY_FONT, 11))
        self.note_label.pack(fill='x')
        actions = tk.Frame(body, bg=PANEL)
        actions.pack(fill='x', pady=(16, 0))
        Button(actions, 'Copy pairing link', command=self.copy_link).pack(side='left')
        Button(actions, 'Done', kind='primary', command=self.close, width=110).pack(side='right')
        self.refresh_code()
        self.geometry(f'510x{min(730, self.winfo_screenheight()-80)}')
        self.update_idletasks()
        height = min(self.winfo_screenheight()-80, body.winfo_reqheight()+68)
        x = max(0, parent.winfo_rootx()+(parent.winfo_width()-510)//2)
        y = max(0, parent.winfo_rooty()+(parent.winfo_height()-height)//2)
        self.geometry(f'510x{height}+{x}+{y}')
        self.check()

    def refresh_code(self, event=None):
        import qrcode
        link = self.bridge.pairing_link(self.address.get())
        if not link:
            return
        code = qrcode.QRCode(box_size=4, border=4)
        code.add_data(link)
        code.make(fit=True)
        output = io.BytesIO()
        code.make_image(fill_color='black', back_color='white').save(output, format='PNG')
        self.picture = tk.PhotoImage(master=self, data=base64.b64encode(output.getvalue()))
        self.image.configure(image=self.picture)

    def copy_link(self):
        link = self.bridge.pairing_link(self.address.get())
        if link:
            self.clipboard_clear()
            self.clipboard_append(link)
            self.note.set('Paste the link into the phone app, then tap Connect.')

    def check(self):
        if self.bridge.paired:
            self.note.set('Phone paired. You can close this window.')
        elif not self.bridge.pairing_link(self.address.get()):
            self.note.set('Code expired. Close this window and choose Pair phone again.')
            self.note_label.configure(fg=RED)
            self.image.configure(image='')
        self.timer = self.after(500, self.check)

    def close(self):
        if self.timer:
            self.after_cancel(self.timer)
        self.destroy()
