"""UI checks use temporary profiles and never record input or lock the PC."""
import copy
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app import App
from dialogs import Dialog
from test_profiles import profile
from test_workflow import ImmediateExecutor
from ui_theme import configure


class PageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ui-test-', dir=Path(__file__).resolve().parent/'data')
        self.addCleanup(self.temporary.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        for target in ('dashboard.paint_map', 'dashboard.load_logo', 'dashboard.set_icon'):
            mocked = patch(target, return_value=None)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.app = App(self.root, self.temporary.name, executor=ImmediateExecutor(), locker=lambda: True)
        if self.app.timer is not None:
            self.root.after_cancel(self.app.timer)
            self.app.timer = None
        self.addCleanup(self.app.close)

    def test_navigation_keeps_training_and_tracking_unchanged(self):
        identifier = self.app.store.create(profile())
        self.app.load_profile(identifier)
        before = copy.deepcopy(self.app.profile)
        for name in self.app.pages:
            self.app.show_page(name)
            self.assertEqual(self.app.current_page, name)
            self.assertEqual(self.app.profile, before)
            self.assertFalse(self.app.active)
            self.assertFalse(self.app.consent.get())

    def test_overview_training_action_opens_the_training_page(self):
        self.app.start_button.invoke()
        self.assertEqual(self.app.current_page, 'training')
        self.assertFalse(self.app.active)

    def test_trained_profile_shows_add_training_and_untrained_profile_shows_duration(self):
        identifier = self.app.store.create(profile())
        self.app.load_profile(identifier)
        self.assertEqual(self.app.training_controls.winfo_manager(), 'pack')
        self.assertEqual(self.app.training_ready.winfo_manager(), '')
        self.app.mode, self.app.ai = 'monitor', object()
        self.app.update_progress()
        self.assertEqual(self.app.training_controls.winfo_manager(), '')
        self.assertEqual(self.app.training_ready.winfo_manager(), 'pack')
        self.assertEqual(self.app.learn_button.text, 'Add training')

    def test_cancelling_password_does_not_show_an_incorrect_password_error(self):
        identifier = self.app.store.create(profile())
        self.app.load_profile(identifier)
        self.app.consent.set(True)
        with patch('app.simpledialog.askstring', return_value=None), patch('app.messagebox.showerror') as error:
            self.app.start()
        error.assert_not_called()
        self.assertFalse(self.app.active)

    def test_all_pages_fit_horizontally_in_small_and_large_windows(self):
        self.app.profile_name.set('A very long profile name with forty chars')
        self.app.speed_text.set('12,345 px/s')
        self.app.dwell_text.set('12,345 ms')
        self.app.edge_text.set('100.0%')
        self.root.deiconify()
        for width, height in ((940, 620), (1220, 780)):
            self.root.geometry(f'{width}x{height}')
            for name in self.app.pages:
                self.app.show_page(name)
                self.root.update_idletasks()
                def inspect(widget):
                    if widget.master is not None and widget.winfo_viewable() and widget.winfo_manager() and widget.master is not self.root:
                        with self.subTest(width=width, page=name, widget=str(widget)):
                            self.assertGreaterEqual(widget.winfo_x(), -1)
                            self.assertLessEqual(widget.winfo_x()+widget.winfo_width(), widget.master.winfo_width()+2)
                            if isinstance(widget, tk.Label) and not float(str(widget.cget('wraplength'))):
                                self.assertLessEqual(widget.winfo_reqwidth(), widget.winfo_width()+2)
                    for child in widget.winfo_children():
                        inspect(child)
                inspect(self.root)


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        configure(self.root)
        mocked = patch('dialogs.load_logo', return_value=None)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.addCleanup(self.root.destroy)

    def dialog(self, **kwargs):
        result = Dialog(self.root, 'Profile password', 'Enter your password to continue.', **kwargs)
        self.addCleanup(lambda: result.destroy() if result.winfo_exists() else None)
        return result

    def test_password_visibility_toggle_preserves_input_and_submit_clears_field(self):
        dialog = self.dialog(entry=True, secret=True)
        self.assertEqual(dialog.entry.cget('show'), '*')
        dialog.value.set('synthetic password')
        dialog.password_toggle.toggle()
        self.assertEqual(dialog.entry.cget('show'), '')
        self.assertEqual(dialog.value.get(), 'synthetic password')
        dialog.password_toggle.toggle()
        self.assertEqual(dialog.entry.cget('show'), '*')
        dialog.submit()
        self.assertEqual(dialog.result, 'synthetic password')
        self.assertEqual(dialog.value.get(), '')

    def test_cancelled_input_returns_none_and_clears_field(self):
        dialog = self.dialog(entry=True, secret=True)
        dialog.value.set('synthetic password')
        dialog.cancel()
        self.assertIsNone(dialog.result)
        self.assertEqual(dialog.value.get(), '')

    def test_question_keeps_yes_and_no_results(self):
        yes = self.dialog(question=True)
        yes.submit()
        self.assertIs(yes.result, True)
        no = self.dialog(question=True)
        no.cancel()
        self.assertIs(no.result, False)

    def test_desktop_approval_displays_code_and_removes_dimmer_after_answer(self):
        dialog = Dialog(self.root, 'Is this you?', 'Test behavior', question=True,
                        desktop_alert=True, code='007')
        overlays = []

        def inspect_then_answer():
            overlays.extend(window for window in self.root.winfo_children() if window is not dialog)
            dialog.accept_button.invoke()

        dialog.after(150, inspect_then_answer)
        numbers = [label.cget('text') for label in dialog.code_panel.body.winfo_children()]
        self.assertIn('007', numbers)
        self.assertTrue(dialog.show())
        self.assertEqual(len(overlays), 1)
        self.assertFalse(overlays[0].winfo_exists())

    def test_modal_returns_input_and_releases_grab(self):
        dialog = self.dialog(entry=True, secret=True)
        dialog.value.set('synthetic password')
        dialog.after(100, dialog.submit)
        self.assertEqual(dialog.show(), 'synthetic password')
        self.assertIsNone(self.root.grab_current())

    def test_password_dialog_is_compact_and_contains_its_controls(self):
        dialog = self.dialog(entry=True, secret=True)
        dialog.deiconify()
        dialog.update_idletasks()
        self.assertLessEqual(dialog.winfo_height(), 380)
        self.assertLessEqual(dialog.content.body.winfo_reqheight()+72, dialog.winfo_height()+2)
        button_bottom = dialog.accept_button.winfo_rooty()+dialog.accept_button.winfo_height()
        self.assertLess(button_bottom, dialog.winfo_rooty()+dialog.winfo_height()-12)


if __name__ == '__main__':
    unittest.main()
