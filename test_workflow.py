"""Full desktop workflows using a fake clock, simulated input and a mocked Windows lock."""
import copy
from concurrent.futures import Future
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch, PropertyMock

from app import App, MIN_WINDOWS, password_hash
from metrics import Collector, MouseHeatmap, ScreenLayout
from test_metrics import FakeInput
from test_profiles import profile


class ImmediateExecutor:
    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as error:
            future.set_exception(error)
        return future

    def shutdown(self, **kwargs):
        pass


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parent/'data'
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='workflow-test-', dir=temporary_root)
        self.assertTrue(Path(self.temporary.name).resolve().is_relative_to(temporary_root))
        self.addCleanup(self.temporary.cleanup)
        self.now = 0.0
        self.root = tk.Tk()
        self.root.withdraw()
        for target in ('dashboard.paint_map', 'dashboard.set_icon', 'dashboard.load_logo'):
            mocked = patch(target, return_value=None)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.user = FakeInput()
        self.layout = ScreenLayout(((0, 0, 1000, 1000),))
        self.collector = Collector(self.user, lambda: self.now, lambda: self.layout)
        self.locker = Mock(return_value=True)
        with patch('app.Collector', return_value=self.collector):
            self.app = App(self.root, self.temporary.name, clock=lambda: self.now,
                           locker=self.locker, executor=ImmediateExecutor())
        self.addCleanup(self.close_app)

    def close_app(self):
        if not self.app.closed:
            self.root.update_idletasks()
            self.app.close()

    def ready_profile(self, name='Oak', base=100):
        data = profile(name, base)
        approved = MouseHeatmap(self.layout)
        approved.add(500, 500, 10)
        data['approved_heatmaps'] = {self.layout.identifier: approved.to_dict()}
        data['training'] = {'duration_seconds': 60, 'elapsed_seconds': 60, 'complete': True}
        return data

    def load(self, data=None):
        identifier = self.app.store.create(data or self.ready_profile())
        self.app.load_profile(identifier)
        return identifier

    def frame(self):
        heatmap = MouseHeatmap(self.layout)
        heatmap.add(900, 900, .5)
        return {'keyboard': [800, 900, 200], 'mouse': [1200, 400, 2, .95],
                'heatmap': heatmap.to_dict(), 'active': True}

    def speed_frame(self, speed):
        return {'keyboard': None, 'mouse': [speed, 9000, 3, 1],
                'mouse_peak_speed': speed, 'active': True}

    def test_double_dwell_alert_is_instant_and_approval_saves_detected_minus_one(self):
        identifier = self.load()
        self.app.profile['key_dwell_max_ms'] = 500
        self.app.consent.set(True)
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            self.app.process({'held_durations': [(1, 1000)]}, 0)
            prompt.assert_not_called()
            self.app.process({'held_durations': [(1, 1001)]}, .5)
            self.assertEqual(prompt.call_count, 1)
            self.assertEqual(self.app.profile['key_dwell_max_ms'], 1000)
            self.app.process({'held_durations': [(2, 2000)]}, 1)
            self.assertEqual(prompt.call_count, 1)
            self.app.process({'held_durations': [(2, 2001)]}, 1.5)
            self.assertEqual(prompt.call_count, 2)
        self.assertEqual(self.app.store.load(identifier)['key_dwell_max_ms'], 2000)
        self.assertEqual(self.app.gate.grace_until, 0)

    def test_protection_updates_current_map_without_overwriting_recorded_behavior(self):
        identifier = self.load()
        recorded = copy.deepcopy(self.app.profile['approved_heatmaps'])
        self.app.profile['mouse_speed_limit'] = 1e9
        self.app.active = True
        self.app.consent.set(True)
        self.user.position = (900, 900)
        for step in range(1, 41):
            self.tick_at(step*.05)
        self.app.save()
        self.assertEqual(self.app.profile['approved_heatmaps'], recorded)
        self.assertGreater(self.collector.current_heatmap.seconds, 1)
        stored = self.app.store.load(identifier)
        self.assertTrue(stored['current_heatmaps'])
        self.app.load_profile(identifier)
        self.assertGreater(self.collector.current_heatmap.seconds, 1)
        self.assertEqual(self.app.profile['approved_heatmaps'], recorded)

    def test_outside_map_alert_uses_selected_mode_and_only_approved_updates_change_recorded_map(self):
        self.load()
        self.app.sensitivity.set('Low')
        self.app.consent.set(True)
        frame = {'cursor_position': (900, 900), 'heatmap': self.frame()['heatmap'], 'active': True}
        before = copy.deepcopy(self.app.profile['approved_heatmaps'])
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            for step in range(5):
                self.app.process(frame, step*.5)
            prompt.assert_not_called()
            self.assertEqual(self.app.profile['approved_heatmaps'], before)
            self.now = 2.5
            self.app.process(frame, self.now)
        prompt.assert_called_once()
        self.assertEqual(self.app.profile['last_alert']['kind'], 'mouse_area')
        self.assertNotEqual(self.app.profile['approved_heatmaps'], before)
        self.assertTrue(self.app.learn_positions)

    def test_detection_mode_is_saved_with_the_profile(self):
        identifier = self.load()
        self.app.sensitivity.set('High')
        self.app.save()
        self.app.sensitivity.set('Low')
        self.app.profile = None
        self.app.load_profile(identifier)
        self.assertEqual(self.app.sensitivity.get(), 'High')

    def test_mouse_cap_approval_is_saved_and_a_higher_speed_prompts_again_immediately(self):
        identifier = self.load()
        self.app.profile['mouse_speed_limit'] = 500
        self.app.consent.set(True)
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            self.app.process(self.speed_frame(900), 0)
            self.assertEqual(prompt.call_count, 1)
            self.assertEqual(self.app.profile['mouse_speed_limit'], 900)
            self.app.process(self.speed_frame(900), .1)
            self.assertEqual(prompt.call_count, 1)
            self.app.process(self.speed_frame(950), .2)
            self.assertEqual(prompt.call_count, 2)
            self.assertIn('Mouse moved too fast', prompt.call_args.args[1])
        self.assertEqual(self.app.store.load(identifier)['mouse_speed_limit'], 950)
        self.assertEqual(self.app.gate.grace_until, 0)

    def test_mouse_speed_remains_protected_during_the_typing_grace_period(self):
        self.load()
        self.app.profile['mouse_speed_limit'] = 500
        self.app.gate.grant_grace(0)
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            self.app.process(self.speed_frame(900), 1)
        prompt.assert_called_once()
        self.assertEqual(self.app.profile['mouse_speed_limit'], 900)

    def test_normal_mouse_movement_and_unusual_cursor_areas_do_not_cause_repeated_alerts(self):
        self.load()
        self.app.profile['mouse_speed_limit'] = 500
        frame = self.speed_frame(400)
        frame['heatmap'] = self.frame()['heatmap']
        with patch('app.messagebox.askyesno') as prompt:
            for step in range(30):
                self.app.process(frame, step*.5)
        prompt.assert_not_called()
        self.assertEqual(self.app.risk_text.get(), 'Protection on')

    def test_rejected_speed_locks_without_raising_the_limit_and_resume_button_is_correct(self):
        self.load()
        self.app.profile['mouse_speed_limit'] = 500
        with patch('app.messagebox.askyesno', return_value=False):
            self.app.process(self.speed_frame(900), 0)
        self.locker.assert_called_once()
        self.assertEqual(self.app.profile['mouse_speed_limit'], 500)
        self.assertEqual(self.app.start_text.get(), 'Start protection')
        self.assertFalse(self.app.start_button.instate(['disabled']))

    def test_single_long_key_hold_alert_has_a_short_reason_and_keeps_saved_details(self):
        identifier = self.load()
        self.app.profile['key_hold_samples'] = [300]*30
        self.app.profile['key_dwell_max_ms'] = 300
        self.app.consent.set(True)
        first = {'keyboard': None, 'mouse': None, 'dwell_events': [(1, 1000)],
                 'held_durations': [], 'key_hold_samples': [1000], 'active': False}
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            self.app.process(first, 0)
            for step in range(1, 12):
                self.now = step*.5
                self.app.process({'active': False}, self.now)
        prompt.assert_called_once()
        text = prompt.call_args.args[1]
        self.assertIn('Long key hold', text)
        self.assertIn('1000 ms', text)
        self.assertEqual(text, 'Long key hold: 1000 ms.')
        self.assertEqual(prompt.call_args.args[0], 'Is this you?')
        self.assertTrue(prompt.call_args.kwargs['desktop_alert'])
        stored = self.app.store.load(identifier)
        self.assertEqual(stored['last_alert']['kind'], 'key_dwell')
        self.assertEqual(stored['last_alert']['reasons'][0]['typical'], 300)
        self.assertEqual(stored['key_dwell_max_ms'], 999)
        self.assertIn('1000 ms', self.app.last_alert_text.get())

    def test_windows_lock_failure_is_logged_without_learning_or_tracking_error(self):
        self.load()
        before = copy.deepcopy(self.app.profile['keyboard'])
        self.locker.side_effect = OSError(5, 'Access denied')
        with patch('app.messagebox.askyesno', return_value=False), patch('app.messagebox.showerror') as error:
            self.app.ask_identity(self.frame())
        error.assert_called_once_with('Could not lock PC', 'Windows blocked locking. Press Windows + L.', parent=self.root)
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.risk_text.get(), 'Paused')
        self.assertEqual(self.app.profile['keyboard'], before)
        self.assertIn('Access denied', (Path(self.temporary.name)/'errors.log').read_text(encoding='utf-8'))

    def test_idle_alert_contains_only_reason_and_identity_question(self):
        self.load()
        reason = {'kind': 'cursor_idle', 'observed': 8.6, 'limit': 8.4,
                  'text': 'Cursor stayed still for 8.6s.'}
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            self.app.ask_identity(self.frame(), [reason], event_kind='cursor_idle')
        self.assertEqual(prompt.call_args.args[0], 'Is this you?')
        self.assertEqual(prompt.call_args.args[1], 'Cursor stayed still for 8.6s.')
        self.assertTrue(prompt.call_args.kwargs['desktop_alert'])

    def test_training_saves_actual_peak_speed_instead_of_the_mean(self):
        self.load(profile())
        self.app.record_frame({'keyboard': None, 'mouse': [200, 50, .4, .1],
                               'mouse_peak_speed': 1200, 'key_hold_samples': [300]}, approved=True)
        self.assertEqual(self.app.profile['mouse_peak_learning'], 1200)
        self.app.profile['approved_heatmaps'] = self.ready_profile()['approved_heatmaps']
        self.app.finish_learning()
        self.assertEqual(self.app.profile['mouse_speed_limit'], 1200)

    def test_speed_alone_alerts_after_the_selected_delay_and_approval_saves_it(self):
        identifier = self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        self.app.consent.set(True)
        frame = {'typing_speed': 20, 'typing_active': True, 'active': True}
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            for step in range(10):
                self.now = step*.5
                self.app.process(frame, self.now)
            prompt.assert_not_called()
            self.now = 5
            self.app.process(frame, self.now)
        prompt.assert_called_once()
        stored = self.app.store.load(identifier)
        self.assertEqual(stored['last_alert']['kind'], 'typing_speed')
        self.assertEqual(stored['typing_speed_samples'][-1], 20)
        self.assertEqual(self.app.gate.grace_until, 65)
        self.assertGreater(self.app.typing_history[-1][1], .65)

    def test_speed_graph_rises_even_when_the_rhythm_score_is_normal(self):
        self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        with patch.object(self.app.ai, 'assess_typing_rhythm', return_value=(.3, {})):
            self.app.process({'keyboard': [100, 200, 40], 'typing_speed': 5, 'typing_active': True}, 0)
            self.app.process({'keyboard': [100, 200, 40], 'typing_speed': 20, 'typing_active': True}, .5)
        self.assertLess(self.app.typing_history[0][1], .65)
        self.assertGreater(self.app.typing_history[1][1], .65)
        self.assertEqual(self.app.typing_history[1][0], .3)
        speed_line = self.app.chart.find_withtag('typing_speed')
        self.assertTrue(speed_line)
        coordinates = self.app.chart.coords(speed_line[-1])
        self.assertLess(coordinates[-1], coordinates[1])

    def test_typing_first_mode_suspends_idle_area_and_mouse_speed_checks(self):
        self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        self.app.profile['mouse_speed_limit'] = 500
        frame = {'typing_speed': 5, 'typing_active': True, 'cursor_position': (900, 900), 'mouse_peak_speed': 9000}
        with patch('app.messagebox.askyesno') as prompt:
            for step in range(81):
                self.app.process(frame, step*.5)
        prompt.assert_not_called()
        self.assertIsNone(self.app.spatial_watch.outside_since)
        self.assertIn('paused while typing', self.app.mouse_check_status.get())

    def test_check_both_still_checks_mouse_areas_during_typing(self):
        self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        self.app.set_mouse_mode(False)
        frame = {'typing_speed': 5, 'typing_active': True, 'cursor_position': (900, 900)}
        with patch('app.messagebox.askyesno', return_value=False) as prompt:
            for step in range(11):
                self.app.process(frame, step*.5)
        prompt.assert_called_once()
        self.assertEqual(self.app.profile['last_alert']['kind'], 'mouse_area')
        self.locker.assert_called_once()

    def test_resuming_mouse_starts_fresh_timers_and_discards_paused_speed_bursts(self):
        self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        self.app.profile['mouse_speed_limit'] = 500
        self.collector.recent['bursts'].append((10, 9000))
        with patch('app.messagebox.askyesno', return_value=False) as prompt:
            for step in range(21):
                self.app.process({'typing_speed': 5, 'typing_active': True, 'cursor_position': (900, 900)}, step*.5)
            self.app.process({'typing_active': False, 'cursor_position': (900, 900), 'mouse_peak_speed': 9000}, 10.5)
            for step in range(22, 31):
                self.app.process({'typing_active': False, 'cursor_position': (900, 900)}, step*.5)
            prompt.assert_not_called()
            self.app.process({'typing_active': False, 'cursor_position': (900, 900)}, 15.5)
        prompt.assert_called_once()
        self.assertEqual(self.app.profile['last_alert']['kind'], 'mouse_area')
        self.assertFalse(self.collector.recent['bursts'])

    def test_mouse_mode_buttons_are_saved_separately_for_each_profile(self):
        first = self.load()
        self.app.both_inputs_button.invoke()
        self.assertFalse(self.app.pause_mouse_while_typing.get())
        second = self.app.store.create(self.ready_profile('Second'))
        self.app.load_profile(second)
        self.assertTrue(self.app.pause_mouse_while_typing.get())
        self.app.load_profile(first)
        self.assertFalse(self.app.pause_mouse_while_typing.get())
        self.assertEqual(self.app.both_inputs_button.kind, 'selected')

    def test_pausing_mouse_checks_does_not_disable_key_dwell_detection(self):
        self.load()
        self.app.profile['key_dwell_max_ms'] = 300
        with patch('app.messagebox.askyesno', return_value=False):
            self.app.process({'typing_active': True, 'held_durations': [(1, 1000)]}, 0)
        self.assertEqual(self.app.profile['last_alert']['kind'], 'key_dwell')
        self.locker.assert_called_once()

    def test_typing_speed_is_learned_only_during_training_or_approval(self):
        self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        self.app.record_frame({'typing_speed': 20}, approved=False)
        self.assertEqual(self.app.profile['typing_speed_samples'], [5]*20)
        self.app.record_frame({'typing_speed': 20}, approved=True)
        self.assertEqual(self.app.profile['typing_speed_samples'][-1], 20)

    def test_real_press_trace_flags_mashing_without_mouse_idle_or_long_holds(self):
        self.load()
        self.app.profile['typing_speed_samples'] = [5]*20
        self.app.consent.set(True)
        self.app.active = True
        self.user.position = (900, 900)
        with patch.object(self.app.ai, 'assess_typing_rhythm', return_value=(.3, {})), \
                patch('app.messagebox.askyesno', return_value=False) as prompt:
            for step in range(1, 321):
                self.user.keys = {65} if step % 8 in (1, 2) else set()
                self.tick_at(step*.025)
            prompt.assert_not_called()
            for step in range(321, 641):
                self.user.keys = {65, 66, 67, 68} if step % 4 in (1, 2) else set()
                self.tick_at(step*.025)
        prompt.assert_called_once()
        self.assertEqual(self.app.profile['last_alert']['kind'], 'typing_speed')
        self.assertEqual(self.app.profile['typing_speed_samples'], [5]*20)
        self.locker.assert_called_once()

    def test_phone_yes_uses_the_same_approval_and_grace_period(self):
        self.load()
        self.app.consent.set(True)
        before = len(self.app.profile['keyboard'])
        with patch.object(type(self.app.phone), 'paired', new_callable=PropertyMock, return_value=True), \
                patch('phone_ui.ask_with_phone', return_value=(True, 'phone')) as question:
            self.app.ask_identity(self.frame())
        question.assert_called_once()
        self.assertEqual(len(self.app.profile['keyboard']), before+1)
        self.assertEqual(self.app.gate.grace_until, 60)
        self.assertTrue(self.app.active)
        self.locker.assert_not_called()

    def test_phone_no_requests_the_same_windows_lock_without_learning(self):
        self.load()
        before = copy.deepcopy(self.app.profile['keyboard'])
        with patch.object(type(self.app.phone), 'paired', new_callable=PropertyMock, return_value=True), \
                patch('phone_ui.ask_with_phone', return_value=(False, 'phone')):
            self.app.ask_identity(self.frame())
        self.locker.assert_called_once()
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.profile['keyboard'], before)

    def test_no_on_the_phone_test_never_locks_windows(self):
        self.load()
        with patch.object(type(self.app.phone), 'paired', new_callable=PropertyMock, return_value=True), \
                patch('phone_ui.ask_with_phone', return_value=(False, 'phone')), \
                patch('app.messagebox.showinfo') as info:
            self.app.test_phone()
        self.locker.assert_not_called()
        self.assertIn('phone answered No', info.call_args.args[1])

    def tick_at(self, now):
        if self.app.timer is not None:
            self.root.after_cancel(self.app.timer)
        self.now = now
        self.app.tick()

    def test_new_profile_short_password_explains_and_retries(self):
        with patch('app.simpledialog.askstring', side_effect=[
                'New user', 'short', 'valid test password', 'valid test password']), \
                patch('app.messagebox.showerror') as error:
            self.assertTrue(self.app.new_profile())
        error.assert_called_once()
        self.assertIn('10 characters', error.call_args.args[1])
        stored = self.app.store.load(self.app.profile_id)
        self.assertEqual(stored['name'], 'New user')
        self.assertEqual(stored['password'], password_hash('valid test password', stored['salt']))

    def test_new_profile_confirmation_mismatch_can_retry(self):
        with patch('app.simpledialog.askstring', side_effect=[
                'New user', 'valid test password', 'different test password',
                'valid test password', 'valid test password']), patch('app.messagebox.showerror') as error:
            self.assertTrue(self.app.new_profile())
        error.assert_called_once()

    def test_profile_save_failure_explains_and_preserves_existing_profile(self):
        identifier = self.load()
        with patch('app.simpledialog.askstring', side_effect=['New user', 'test password', 'test password']), \
                patch.object(self.app.store, 'create', side_effect=PermissionError('Read-only storage')), \
                patch('app.messagebox.showerror') as error:
            self.assertFalse(self.app.new_profile())
        self.assertIn('Read-only storage', error.call_args.args[1])
        self.assertEqual(self.app.profile_id, identifier)

    def test_cancel_does_not_create_a_profile(self):
        with patch('app.simpledialog.askstring', side_effect=['Cancelled user', None]):
            self.assertFalse(self.app.new_profile())
        self.assertEqual(self.app.store.entries(), [])

    def test_selected_learning_time_replaces_the_old_window_counter(self):
        empty = profile()
        empty['keyboard'], empty['mouse'] = [], []
        self.load(empty)
        self.app.duration_value.set('10')
        self.app.duration_unit.set('seconds')
        self.app.consent.set(True)
        with patch.object(self.app, 'authenticate', return_value=True):
            self.app.start()
        for step in range(1, 199):
            self.user.keys = {65} if (step//2) % 2 else set()
            self.user.position = (100+step % 60*10, 100+(step % 2)*15)
            self.tick_at(step*.05)
        self.assertEqual(self.app.mode, 'train')
        self.assertLess(self.app.profile['training']['elapsed_seconds'], 10)
        for step in range(199, 204):
            self.user.keys = {65} if (step//2) % 2 else set()
            self.user.position = (100+step % 60*10, 100+(step % 2)*15)
            self.tick_at(step*.05)
        self.assertEqual(self.app.mode, 'monitor')
        self.assertTrue(self.app.active)
        self.assertTrue(self.app.profile['training']['complete'])
        self.assertEqual(self.app.ai.dimensions, {'keyboard': 3, 'mouse': 4})
        self.assertIn('complete', self.app.progress.get())

    def test_idle_training_finishes_on_time_and_asks_for_activity_instead_of_crashing(self):
        empty = profile()
        empty['keyboard'], empty['mouse'] = [], []
        self.load(empty)
        self.app.profile['training']['elapsed_seconds'] = 300
        with patch('app.messagebox.showinfo') as message:
            self.app.finish_learning()
        message.assert_called_once()
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.profile['training']['complete'])
        self.assertIsNone(self.app.ai)

    def test_pause_and_restart_restore_countdown_and_saved_heatmap(self):
        data = profile()
        identifier = self.load(data)
        self.app.profile['training']['elapsed_seconds'] = 42
        self.collector.heatmap.add(500, 500, 3)
        self.app.pause()
        self.root.update_idletasks()
        self.app.close()
        self.root = tk.Tk()
        self.root.withdraw()
        self.collector = Collector(self.user, lambda: self.now, lambda: self.layout)
        with patch('app.Collector', return_value=self.collector):
            self.app = App(self.root, self.temporary.name, clock=lambda: self.now,
                           locker=self.locker, executor=ImmediateExecutor())
        self.assertEqual(self.app.profile_id, identifier)
        self.assertEqual(self.app.profile['training']['elapsed_seconds'], 42)
        self.assertAlmostEqual(self.collector.heatmap.seconds, 3)
        self.assertIn('04:18', self.app.progress.get())

    def test_close_writes_heatmap_to_disk(self):
        identifier = self.load()
        self.collector.heatmap.add(100, 100, 2)
        self.root.update_idletasks()
        self.app.close()
        from profiles import ProfileStore
        stored = ProfileStore(self.temporary.name).load(identifier)
        self.assertAlmostEqual(MouseHeatmap.from_dict(stored['heatmaps'][self.layout.identifier]).seconds, 2)

    def test_profiles_keep_their_own_saved_maps_and_models(self):
        first = self.load()
        self.collector.heatmap.add(100, 100, 2)
        second = self.app.store.create(self.ready_profile('Second user', 800))
        self.app.load_profile(second)
        self.assertEqual(self.collector.heatmap.seconds, 0)
        self.collector.heatmap.add(900, 900, 4)
        self.app.load_profile(first)
        self.assertEqual(self.collector.heatmap.seconds, 2)
        self.assertFalse(self.app.active)
        self.assertFalse(self.app.consent.get())

    def test_changing_the_time_updates_the_countdown_before_start(self):
        self.load(profile())
        self.app.duration_value.set('30')
        self.app.duration_unit.set('seconds')
        self.assertEqual(self.app.progress.get(), '00:30 left')
        self.assertEqual(float(self.app.training_bar['maximum']), 30)

    def test_old_three_feature_mouse_data_is_kept_until_timed_learning_finishes(self):
        old = profile(dimensions=3)
        self.load(old)
        before = copy.deepcopy(self.app.profile['mouse'])
        for _ in range(MIN_WINDOWS):
            self.app.record_frame(self.frame(), approved=True)
        self.assertEqual(self.app.profile['mouse'], before)
        self.assertEqual(len(self.app.profile['mouse_enrollment']), MIN_WINDOWS)
        self.app.consent.set(True)
        self.app.finish_learning()
        self.assertEqual(len(self.app.profile['mouse'][0]), 4)
        self.assertNotIn('mouse_enrollment', self.app.profile)
        self.assertEqual(self.app.mode, 'monitor')

    def test_normal_monitoring_does_not_learn_unapproved_behavior(self):
        self.load()
        approved = copy.deepcopy(self.app.profile['approved_heatmaps'])
        keyboard = copy.deepcopy(self.app.profile['keyboard'])
        self.collector.heatmap.add(900, 900, 10)
        self.app.process({'keyboard': [100, 160, 40], 'mouse': [300, 80, .4, .1], 'active': True}, 0)
        self.app.save()
        self.assertEqual(self.app.profile['approved_heatmaps'], approved)
        self.assertEqual(self.app.profile['keyboard'], keyboard)

    def test_yes_learns_behavior_and_grants_one_minute_without_alerts(self):
        self.load()
        self.app.active = True
        self.app.consent.set(True)
        before = len(self.app.profile['keyboard'])
        with patch('app.messagebox.askyesno', return_value=True) as prompt:
            for step in range(12):
                self.now = step*.5
                self.app.process(self.frame(), self.now)
            self.assertEqual(prompt.call_count, 1)
            self.assertEqual(self.app.gate.grace_until, 65)
            for now in (6, 30, 60, 64.9):
                self.now = now
                self.app.process(self.frame(), now)
            self.assertEqual(prompt.call_count, 1)
        self.assertEqual(len(self.app.profile['keyboard']), before+1)
        self.assertTrue(self.app.active)
        self.locker.assert_not_called()

    def test_new_behavior_is_saved_during_grace_and_retrained_when_it_ends(self):
        self.load()
        self.app.consent.set(True)
        with patch('app.messagebox.askyesno', return_value=True):
            self.app.ask_identity(self.frame())
        before = len(self.app.profile['keyboard'])
        self.app.record_frame(self.frame(), approved=bool(self.app.gate.grace_left(30)))
        self.assertEqual(len(self.app.profile['keyboard']), before+1)
        self.tick_at(60)
        self.assertEqual(self.app.mode, 'monitor')
        self.assertTrue(self.app.active)
        self.assertEqual(self.app.gate.grace_until, 0)
        self.assertIsNone(self.app.gate.since)

    def test_no_calls_windows_lock_and_does_not_learn_the_changes(self):
        self.load()
        before = copy.deepcopy(self.app.profile['keyboard'])
        with patch('app.messagebox.askyesno', return_value=False):
            for step in range(12):
                self.app.process(self.frame(), step*.5)
        self.locker.assert_called_once()
        self.assertFalse(self.app.active)
        self.assertEqual(self.app.profile['keyboard'], before)

    def test_continuity_break_prevents_an_alert(self):
        self.load()
        with patch('app.messagebox.askyesno') as prompt:
            for step in range(9):
                self.app.process(self.frame(), step*.5)
            self.app.process({'active': False}, 4.5)
            self.app.process(self.frame(), 5)
            prompt.assert_not_called()

    def test_poll_error_is_logged_and_timer_keeps_running(self):
        self.load()
        self.app.active = True
        self.app.consent.set(True)
        with patch.object(self.collector, 'poll', side_effect=RuntimeError('Simulated input failure')), \
                patch('app.messagebox.showerror') as message:
            self.tick_at(.1)
        self.assertFalse(self.app.active)
        self.assertIsNotNone(self.app.timer)
        self.assertIn('Simulated input failure', (Path(self.temporary.name)/'errors.log').read_text())
        message.assert_called_once()

    def test_failed_model_fit_is_recoverable(self):
        self.load()
        future = Future()
        future.set_exception(RuntimeError('Simulated training failure'))
        self.app.future = future
        self.app.future_token = (self.app.fit_token, self.app.profile_id)
        self.app.mode = 'building'
        with patch('app.messagebox.showerror') as message:
            self.tick_at(.1)
        message.assert_called_once()
        self.assertEqual(self.app.mode, 'train')
        self.assertFalse(self.app.start_button.instate(['disabled']))
        self.assertFalse(self.app.active)

    def test_clear_heatmap_is_saved_without_erasing_learned_behavior(self):
        self.load()
        self.collector.current_heatmap.add(100, 100, 10)
        approved = copy.deepcopy(self.app.profile['approved_heatmaps'])
        with patch('app.messagebox.askyesno', return_value=True):
            self.app.reset_heatmap()
        self.assertEqual(self.collector.current_heatmap.seconds, 0)
        self.assertEqual(self.app.profile['approved_heatmaps'], approved)


if __name__ == '__main__':
    unittest.main()
