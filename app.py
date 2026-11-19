"""BehaviorGuard: timed learning, saved mouse maps, and continuous protection."""
import copy
import ctypes
import faulthandler
import hashlib
import hmac
import logging
import math
import os
from pathlib import Path
import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from dialogs import messagebox, simpledialog

from sklearn.ensemble import IsolationForest
from detection import (CHECK_SECONDS, MAX_SAMPLES, MIN_SAMPLES, SAMPLE_SECONDS,
                       DwellWatch, PositionModel, ThreatTimer, clock_text, duration_seconds,
                       dwell_limits, learned_mouse_limit, speed_reason, alert_delay,
                       assess_typing_speed, typing_speed_band)
from heatmap import HeatField, SpatialWatch
from metrics import Collector, MouseHeatmap, mean, vector
from profiles import ProfileStore
from phone_bridge import PhoneBridge

DATA = Path(__file__).resolve().parent/'data'
MIN_WINDOWS = MIN_SAMPLES
FEATURES = {'keyboard': ('hold_ms', 'interval_ms', 'interval_variation'),
            'mouse': ('speed', 'speed_variation', 'turn_radians', 'edge_fraction')}
FLOORS = {'keyboard': (20, 40, 20), 'mouse': (80, 60, .2, .05)}
THRESHOLDS = {'Low': .65, 'Balanced': .65, 'High': .65}


def score(kind, value, baseline):
    centers = [st.median(col) for col in zip(*baseline)]
    scales = [max(floor, 1.4826*st.median(abs(row[i]-centers[i]) for row in baseline))
              for i, floor in enumerate(FLOORS[kind][:len(centers)])]
    differences = [abs(v-c)/s for v, c, s in zip(value, centers, scales)]
    return mean(sorted(differences, reverse=True)[:2]), dict(zip(FEATURES[kind], differences))


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()


def lock_windows():
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.LockWorkStation.argtypes = []
    user.LockWorkStation.restype = ctypes.c_int
    ctypes.set_last_error(0)
    if not user.LockWorkStation():
        raise ctypes.WinError(ctypes.get_last_error())
    return True


class PersonalAI:
    def __init__(self, profile):
        self.models, self.dimensions = {}, {}
        self.positions = {key: PositionModel(MouseHeatmap.from_dict(data))
                          for key, data in profile.get('approved_heatmaps', {}).items()}
        for kind in FEATURES:
            rows = profile[kind]
            if len(rows) < MIN_SAMPLES:
                raise ValueError('More typing and mouse activity is needed.')
            dimensions = len(rows[0])
            if dimensions not in ((3,) if kind == 'keyboard' else (3, 4)) or any(
                    len(row) != dimensions or not all(math.isfinite(v) for v in row) for row in rows):
                raise ValueError('Invalid saved behavior.')
            model = IsolationForest(n_estimators=150, contamination='auto', random_state=42, n_jobs=1)
            model.fit(rows)
            self.models[kind], self.dimensions[kind] = model, dimensions

    def assess(self, kind, value, baseline):
        value = value[:self.dimensions[kind]]
        anomaly = -float(self.models[kind].score_samples([value])[0])
        _, differences = score(kind, value, baseline)
        # Also check each learned measurement, so a change in one criterion is not hidden.
        individual = min(.95, .40+.05*max(differences.values(), default=0))
        return max(anomaly, individual), differences

    def position_risk(self, heatmap):
        model = self.positions.get(heatmap.layout.identifier)
        return model.assess(heatmap) if model else None

    def assess_typing_rhythm(self, value, baseline):
        # Individual key holds have their own event detector instead of an averaged AI feature.
        adjusted = value[:]
        adjusted[0] = st.median(row[0] for row in baseline)
        risk, details = self.assess('keyboard', adjusted, baseline)
        details.pop('hold_ms', None)
        return risk, details


class App:
    thresholds = THRESHOLDS

    def __init__(self, root, data_directory=None, clock=None, locker=None, executor=None):
        self.root, self.clock = root, clock or time.monotonic
        self.locker = locker or lock_windows
        from branding import APP_NAME
        root.title(APP_NAME)
        self.store = ProfileStore(data_directory or DATA)
        self.phone = PhoneBridge(self.store.directory)
        self.phone_window = None
        self.logger = logging.getLogger(f'behaviorguard.{id(self)}')
        self.logger.setLevel(logging.ERROR)
        self.error_handler = logging.FileHandler(self.store.directory/'errors.log', encoding='utf-8')
        self.logger.addHandler(self.error_handler)
        self.logger.propagate = False
        self.root.report_callback_exception = self.handle_error
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='BehaviorGuard-AI')
        self.future = None
        self.fit_token = 0
        self.resume_after_fit = False
        self.profile_id = self.profile = self.ai = None
        self.active, self.closed, self.reporting_error = False, False, False
        self.mode = 'train'
        self.gate = ThreatTimer()
        self.dwell_watch = DwellWatch()
        self.spatial_watch = SpatialWatch()
        self.learn_positions = False
        self._field_cache = None
        self.history = []
        self.typing_history = []
        self.mouse_was_paused = False
        self.collector = Collector()
        self.last_tick = self.last_check = self.last_save = self.clock()
        self.last_live_update = self.last_heatmap_update = 0
        self.last_phone_update = 0
        self.timer = None
        from dashboard import build
        build(self)
        self.refresh_profiles()
        if self.profile_entries:
            preferred = self.store.selected_profile()
            self.load_profile(preferred if any(key == preferred for key, _ in self.profile_entries)
                              else self.profile_entries[0][0])
        else:
            self.update_progress()
        try:
            self.phone.restore()
        except (OSError, ImportError, ValueError):
            self.logger.exception('Phone connection could not start')
        self.update_phone_status()
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.timer = root.after(25, self.tick)

    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('1.0', time.strftime('%H:%M:%S')+'  '+text+'\n')
        self.log.delete('151.0', 'end')
        self.log.configure(state='disabled')

    def save(self):
        if self.profile is not None:
            self.profile['heatmaps'] = self.collector.saved_heatmaps()
            self.profile['current_heatmaps'] = self.collector.saved_current_maps()
            self.profile['sensitivity_mode'] = self.sensitivity.get()
            self.profile['pause_mouse_while_typing'] = self.pause_mouse_while_typing.get()
            self.store.save(self.profile_id, self.profile)
            self.last_save = self.clock()

    def refresh_profiles(self):
        self.profile_entries = self.store.entries()
        self.profile_selector['values'] = [name for _, name in self.profile_entries]
        index = next((i for i, (key, _) in enumerate(self.profile_entries) if key == self.profile_id), None)
        if index is None:
            self.profile_name.set('Choose a profile')
        else:
            self.profile_selector.current(index)

    def switch_profile(self, event=None):
        index = self.profile_selector.current()
        if index >= 0 and self.profile_entries[index][0] != self.profile_id:
            self.load_profile(self.profile_entries[index][0])

    def load_profile(self, identifier):
        self.pause()
        self.fit_token += 1
        self.future = None
        self.ai = None
        self.gate = ThreatTimer()
        self.dwell_watch.reset()
        self.spatial_watch.reset()
        self.learn_positions = False
        self._field_cache = None
        self.collector.reset_session()
        self.profile_id = self.profile = None
        self.history = []
        self.typing_history = []
        self.mouse_was_paused = False
        self.mode = 'train'
        self.consent.set(False)
        try:
            profile = self.store.load(identifier)
            self.collector.restore_heatmaps(profile.get('heatmaps', {}))
            self.collector.restore_current_maps(profile.get('current_heatmaps', {}))
            profile.setdefault('training', {'duration_seconds': 300, 'elapsed_seconds': 0, 'complete': False})
            self.profile_id, self.profile = identifier, profile
            self.pause_mouse_while_typing.set(profile.get('pause_mouse_while_typing', True))
            profile.setdefault('mouse_speed_limit', learned_mouse_limit(profile))
            limits = dwell_limits(profile)
            profile.setdefault('key_dwell_max_ms', limits[0] if limits else 0)
            mode = {'Relaxed': 'Low', 'Sensitive': 'High'}.get(profile.get('sensitivity_mode'), profile.get('sensitivity_mode', 'Balanced'))
            self.sensitivity.set(mode if mode in THRESHOLDS else 'Balanced')
            previous = profile.get('last_alert', {}).get('reasons', [])
            self.last_alert_text.set('Last alert: '+ '; '.join(r['text'] for r in previous) if previous else 'No alerts recorded for this profile.')
            self.store.remember_selected(identifier)
            seconds = profile['training']['duration_seconds']
            self.duration_value.set(f'{seconds/60:g}' if seconds % 60 == 0 else f'{seconds:g}')
            self.duration_unit.set('minutes' if seconds % 60 == 0 else 'seconds')
            ready = (all(len(profile[k]) >= MIN_SAMPLES for k in FEATURES)
                     and len(profile['mouse'][0]) == 4 and bool(profile.get('approved_heatmaps')))
            if profile['training']['complete'] and ready:
                self.begin_fit(resume=False)
            else:
                profile['training']['complete'] = False
                self.status.set('Open Training to record your usual behavior.')
            self.write_log('Profile opened. Saved behavior and mouse maps restored.')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set('This profile could not be opened.')
            messagebox.showerror('Profile', f'Could not open this profile.\n{exc}', parent=self.root)
        self.refresh_profiles()
        self.update_progress()
        self.update_live()
        self.draw_heatmap()
        self.draw(THRESHOLDS[self.sensitivity.get()])

    def new_profile(self):
        self.pause()
        while True:
            name = simpledialog.askstring('New profile', 'Choose a profile name (up to 40 characters).', parent=self.root)
            if name is None:
                return False
            name = name.strip()
            if name and len(name) <= 40 and not any(n.casefold() == name.casefold() for _, n in self.store.entries()):
                break
            messagebox.showerror('Profile name', 'Use a new name with 1 to 40 characters.', parent=self.root)
        while True:
            password = simpledialog.askstring('Create password', 'Choose a password with at least 10 characters.', show='*', parent=self.root)
            if password is None:
                return False
            if len(password) < 10:
                messagebox.showerror('Password too short', 'Use at least 10 characters. Please try again.', parent=self.root)
                continue
            confirm = simpledialog.askstring('Confirm password', 'Enter your password again.', show='*', parent=self.root)
            if confirm is None:
                return False
            if password == confirm:
                break
            messagebox.showerror('Password', 'Passwords did not match. Please try again.', parent=self.root)
        salt = os.urandom(16).hex()
        profile = {'name': name, 'schema_version': 3, 'salt': salt, 'password': password_hash(password, salt),
                   'keyboard': [], 'mouse': [], 'heatmaps': {}, 'approved_heatmaps': {},
                   'training': {'duration_seconds': 300, 'elapsed_seconds': 0, 'complete': False}}
        try:
            identifier = self.store.create(profile)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Could not create profile', f'Could not save the new profile.\n{exc}', parent=self.root)
            return False
        self.load_profile(identifier)
        self.show_page('training')
        return self.profile_id == identifier

    def authenticate(self):
        password = simpledialog.askstring('Profile password', 'Enter your password to continue.', show='*', parent=self.root)
        if password is None:
            return None
        return self.profile is not None and hmac.compare_digest(
            password_hash(password, self.profile['salt']), self.profile['password'])

    def start(self):
        if self.active or self.future is not None:
            return
        if not self.consent.get():
            messagebox.showinfo('Allow tracking', 'Select the tracking checkbox before starting.', parent=self.root)
            return
        if self.profile is None:
            if not self.new_profile():
                return
            self.consent.set(True)
        else:
            authenticated = self.authenticate()
            if not authenticated:
                if authenticated is not None:
                    messagebox.showerror('Incorrect password', 'That password is not correct. Please try again.', parent=self.root)
                return
        if self.mode == 'train':
            try:
                seconds = duration_seconds(self.duration_value.get(), self.duration_unit.get())
            except ValueError as exc:
                messagebox.showerror('Training duration', str(exc), parent=self.root)
                return
            training = self.profile['training']
            if seconds != training['duration_seconds'] or training['elapsed_seconds'] >= seconds:
                training['elapsed_seconds'] = 0
            training['duration_seconds'], training['complete'] = seconds, False
            if training['elapsed_seconds'] == 0:
                self.profile['mouse_peak_learning'] = 0.0
                self.profile['key_dwell_learning_max_ms'] = 0.0
            self.write_log(f'Training for {clock_text(seconds-training["elapsed_seconds"])}. Type and move the mouse normally.')
        self.collector.clear()
        self.gate.reset()
        self.dwell_watch.reset()
        self.spatial_watch.reset()
        self.mouse_was_paused = False
        self.last_tick = self.last_check = self.clock()
        self.active = True
        self.save()
        self.update_progress()
        self.update_status()

    def learn_more(self):
        if self.profile is None:
            return
        self.pause()
        if not self.authenticate():
            return
        self.fit_token += 1
        self.future = None
        self.profile['training']['complete'] = False
        self.profile['training']['elapsed_seconds'] = 0
        self.mode = 'train'
        self.save()
        self.status.set('Choose a duration, then start training.')
        self.update_progress()
        self.show_page('training')

    def advance_learning_clock(self, now):
        if self.active and self.mode == 'train':
            training = self.profile['training']
            training['elapsed_seconds'] = min(training['duration_seconds'],
                training['elapsed_seconds']+max(0, min(now-self.last_tick, 1)))
        self.last_tick = now

    def record_frame(self, frame, approved=False):
        if not approved:
            return
        rate = frame.get('typing_speed')
        if rate is not None and math.isfinite(rate) and rate > 0:
            rates = self.profile.setdefault('typing_speed_samples',
                [1000/row[1] for row in self.profile['keyboard'] if row[1] > 0][-MAX_SAMPLES:])
            self.profile['typing_speed_samples'] = (rates+[float(rate)])[-MAX_SAMPLES:]
        holds = frame.get('key_hold_samples', [])
        if holds:
            self.profile['key_hold_samples'] = (self.profile.get('key_hold_samples', [])+list(holds))[-1000:]
        if self.mode == 'train':
            peak = frame.get('mouse_peak_speed', 0)
            self.profile['mouse_peak_learning'] = max(self.profile.get('mouse_peak_learning', 0), peak)
            self.profile['key_dwell_learning_max_ms'] = max(self.profile.get('key_dwell_learning_max_ms', 0), max(holds, default=0))
        for kind in FEATURES:
            value = frame.get(kind)
            if value is None:
                continue
            target = 'mouse_enrollment' if kind == 'mouse' and self.profile['mouse'] and len(self.profile['mouse'][0]) == 3 else kind
            rows = self.profile.setdefault(target, [])
            rows.append(value[:])
            self.profile[target] = rows[-MAX_SAMPLES:]
        data = frame.get('heatmap')
        if data and (self.mode == 'train' or self.learn_positions):
            heatmap = MouseHeatmap.from_dict(data)
            if heatmap.seconds:
                approved_maps = self.profile.setdefault('approved_heatmaps', {})
                key = heatmap.layout.identifier
                existing = MouseHeatmap.from_dict(approved_maps[key]) if key in approved_maps else MouseHeatmap(heatmap.layout)
                existing.merge(heatmap)
                approved_maps[key] = existing.to_dict()

    def pause(self):
        self.resume_after_fit = False
        if self.active:
            now = self.clock()
            self.advance_learning_clock(now)
            self.record_frame(self.collector.finish(), self.mode == 'train' or bool(self.gate.grace_left(now)))
        self.active = False
        self.gate.reset()
        self.dwell_watch.reset()
        self.spatial_watch.reset()
        self.mouse_was_paused = False
        self.collector.clear()
        self.practice.delete('1.0', 'end')
        self.save()
        self.status.set('Tracking is paused. Your progress is saved.')
        self.risk_text.set('Paused')
        self.update_progress()
        self.update_live()
        self.draw_heatmap()

    def finish_learning(self):
        self.record_frame(self.collector.finish(), approved=True)
        self.active = False
        keyboard = self.profile['keyboard']
        mouse = self.profile.get('mouse_enrollment', self.profile['mouse'])
        if len(keyboard) < MIN_SAMPLES or len(mouse) < MIN_SAMPLES or not self.profile.get('approved_heatmaps'):
            self.save()
            self.status.set('Training finished, but more activity is needed.')
            self.update_progress()
            missing = []
            if len(keyboard) < MIN_SAMPLES:
                missing.append('type more')
            if len(mouse) < MIN_SAMPLES or not self.profile.get('approved_heatmaps'):
                missing.append('move the mouse more')
            messagebox.showinfo('More activity needed',
                'Your progress is saved. Start another training session and '+ ' and '.join(missing)+'.', parent=self.root)
            return
        if 'mouse_enrollment' in self.profile:
            self.profile['mouse'] = self.profile.pop('mouse_enrollment')
        self.profile['schema_version'] = 3
        self.profile['mouse_speed_limit'] = self.profile.get('mouse_peak_learning', 0) or learned_mouse_limit(self.profile)
        self.profile['key_dwell_max_ms'] = self.profile.get('key_dwell_learning_max_ms', 0) or self.profile.get('key_dwell_max_ms', 0)
        self.save()
        self.begin_fit(resume=True)

    def begin_fit(self, resume):
        self.active = False
        self.resume_after_fit = resume
        self.fit_token += 1
        self.future_token = (self.fit_token, self.profile_id)
        self.mode = 'building'
        self.status.set('Preparing your saved behavior. Please wait.')
        self.future = self.executor.submit(PersonalAI, copy.deepcopy(self.profile))
        self.update_progress()
        self.check_fit()

    def check_fit(self):
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        if self.future_token != (self.fit_token, self.profile_id):
            return
        self.ai = future.result()
        self.learn_positions = False
        self.spatial_watch.reset()
        self._field_cache = None
        self.profile['training']['complete'] = True
        self.mode = 'monitor'
        self.collector.clear()
        self.gate.reset()
        self.save()
        self.active = self.resume_after_fit and self.consent.get()
        self.last_tick = self.last_check = self.clock()
        self.update_progress()
        self.update_status()
        self.write_log('Training saved. Your profile is ready for protection.')
        if self.active:
            self.show_page('overview')

    def recorded_heatmap(self):
        layout = self.collector.layout
        data = self.profile.get('approved_heatmaps', {}).get(layout.identifier) if self.profile else None
        return MouseHeatmap.from_dict(data) if data else MouseHeatmap(layout)

    def recorded_field(self):
        heatmap = self.recorded_heatmap()
        stamp = (self.profile_id, heatmap.layout.identifier, heatmap.samples, heatmap.seconds)
        if self._field_cache is None or self._field_cache[0] != stamp:
            self._field_cache = (stamp, HeatField(heatmap))
        return self._field_cache[1]

    def mode_changed(self, *args):
        self.gate.reset()
        self.spatial_watch.reset()
        delay = alert_delay(self.sensitivity.get())
        self.area_info.set(f'{self.sensitivity.get()}: {delay:g}s in empty areas; up to {delay*5:g}s without moving in red areas.')
        self.draw(THRESHOLDS[self.sensitivity.get()])
        self.draw_heatmap()
        self.update_progress()

    def set_mouse_mode(self, pause_while_typing):
        self.pause_mouse_while_typing.set(pause_while_typing)
        self.mouse_was_paused = False
        self.spatial_watch.reset()
        self.collector.reset_mouse_detection()
        self.update_progress()
        self.save()

    def process(self, values, now=None):
        now = self.clock() if now is None else now
        if self.ai is None:
            return
        rate = values.get('typing_speed')
        typing_active = bool(values.get('typing_active', values.get('active', True) and (
            values.get('keyboard') is not None or rate is not None or values.get('held_durations'))))
        pause_mouse = self.pause_mouse_while_typing.get() and typing_active
        resuming_mouse = self.mouse_was_paused and not pause_mouse
        if pause_mouse or resuming_mouse:
            self.spatial_watch.reset()
            self.collector.reset_mouse_detection()
        self.mouse_was_paused = pause_mouse
        self.mouse_check_status.set('Mouse checks paused while typing.' if pause_mouse else
                                    'Mouse checks running.' if self.active else 'Mouse checks ready.')
        if pause_mouse:
            self.area_info.set('Mouse checks paused while typing.')
        peak = values.get('mouse_peak_speed', 0)
        limit = learned_mouse_limit(self.profile)
        if not pause_mouse and not resuming_mouse and limit > 0 and peak > limit+max(.001, limit*1e-9):
            self.ask_identity(values, [speed_reason(peak, limit)], event_kind='mouse_speed')
            return
        reason = self.dwell_watch.observe(now, values.get('dwell_events', []),
                    values.get('held_durations', []), dwell_limits(self.profile, self.sensitivity.get()))
        if reason:
            self.ask_identity(values, [reason], event_kind='key_dwell')
            return
        if self.gate.grace_left(now):
            self.risk_text.set('Updating profile')
            self.gate.reset()
            self.spatial_watch.reset()
            return
        delay = alert_delay(self.sensitivity.get())
        spatial_reason = None if pause_mouse else self.spatial_watch.update(
            now, values.get('cursor_position'), self.recorded_field(), delay, moving=values.get('mouse_moving', False))
        info = self.spatial_watch.info
        if info:
            self.area_info.set(f'Outside saved areas: {info["outside_elapsed"]:.1f} of {delay:g}s' if info['outside'] else
                               f'Without moving: {info["idle_elapsed"]:.1f} of {info["idle_limit"]:.1f}s')
        if spatial_reason:
            self.ask_identity(values, [spatial_reason], event_kind=spatial_reason['kind'])
            return
        results, reasons = {}, []
        threshold = THRESHOLDS[self.sensitivity.get()]
        speed_assessment = assess_typing_speed(self.profile, rate) if typing_active else None
        if speed_assessment is not None:
            results['typing speed'] = speed_assessment[0]
            if speed_assessment[0] > threshold:
                reasons.append(speed_assessment[1])
        if typing_active and values.get('keyboard') is not None:
            risk, details = self.ai.assess_typing_rhythm(values['keyboard'], self.profile['keyboard'])
            results['typing rhythm'] = risk
            labels = {'interval_ms': ('Time between key presses', 1), 'interval_variation': ('Typing rhythm variation', 2)}
            for name, difference in (sorted(details.items(), key=lambda item: item[1], reverse=True)[:1] if risk > threshold else []):
                title, index = labels[name]
                observed = values['keyboard'][index]
                usual = st.median(row[index] for row in self.profile['keyboard'])
                reasons.append({'kind': name, 'observed': float(observed), 'reference': float(usual),
                    'text': f'{title} changed: {observed:.0f} ms.'})
        if not results or not typing_active:
            self.gate.update(now, False, active=False)
            if values.get('active', True) and peak > 0:
                self.risk_text.set('Protection on')
                self.metric.set('Mouse activity looks normal. Waiting for typing.')
                if self.active:
                    self.status.set('Protection on. Your mouse speed looks normal.')
            else:
                self.risk_text.set('Protection on')
                self.metric.set('Waiting for typing. Pauses do not trigger typing-speed alerts.')
            return
        risk = max(results.values())
        unusual = risk > threshold
        self.risk_text.set('Checking activity' if unusual else 'Protection on')
        self.metric.set('Checking typing speed and rhythm.'+(' Mouse checks are paused while typing.' if pause_mouse else ''))
        self.history = (self.history+[risk])[-120:]
        self.typing_history = (self.typing_history+[(results.get('typing rhythm'), results.get('typing speed'))])[-120:]
        self.draw(threshold)
        alert = self.gate.update(now, unusual, seconds=delay)
        if unusual:
            self.status.set(f'Typing looks different ({self.gate.different_for(now):.1f} / {delay:g}s).')
        elif self.active:
            self.status.set('Your typing and mouse activity look normal.')
        if alert:
            self.ask_identity(values, reasons[:2], event_kind='typing_speed' if reasons and reasons[0]['kind'] == 'typing_speed' else 'behavior')

    def ask_identity(self, values, reasons=None, event_kind='behavior'):
        reasons = reasons or [{'kind': 'typing_change', 'text': 'Your typing rhythm changed from the saved pattern.'}]
        self.active = False
        self.gate.reset()
        self.collector.clear()
        self.spatial_watch.reset()
        self.mouse_was_paused = False
        self.update_progress()
        description = '\n'.join(reason['text'] for reason in reasons)
        self.profile['last_alert'] = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'kind': event_kind, 'reasons': reasons}
        self.last_alert_text.set('Last alert: '+ '; '.join(reason['text'] for reason in reasons))
        self.write_log('Alert: '+ '; '.join(reason['text'] for reason in reasons))
        self.save()
        if self.phone.paired:
            from phone_ui import ask_with_phone
            answer, source = ask_with_phone(self.root, self.phone, description, self.profile.get('name', ''), event_kind)
            self.write_log('Alert answered on your phone.' if source == 'phone' else 'Alert answered on this PC.')
        else:
            answer = messagebox.askyesno('Is this you?', description, parent=self.root, desktop_alert=True)
        if answer:
            if event_kind in ('mouse_area', 'cursor_idle'):
                self.learn_positions = True
            self.record_frame(values, approved=True)
            if event_kind == 'mouse_speed':
                self.profile['mouse_speed_limit'] = max(learned_mouse_limit(self.profile), values['mouse_peak_speed'])
            elif event_kind == 'key_dwell':
                self.profile['key_dwell_max_ms'] = max(0, int(reasons[0]['observed'])-1)
                self.dwell_watch.reset()
            else:
                self.dwell_watch.reset()
                self.gate.grant_grace(self.clock())
            self.collector.clear()
            self.last_tick = self.last_check = self.clock()
            self.active = self.consent.get()
            self.save()
            self.update_status()
            self.update_progress()
            self.write_log('New mouse speed saved.' if event_kind == 'mouse_speed' else
                           'New key hold time saved.' if event_kind == 'key_dwell' else
                           'You approved this activity. Updating your profile for 1 minute.')
        else:
            self.dwell_watch.reset()
            self.learn_positions = False
            self.save()
            self.status.set('Protection paused. Locking this PC...')
            try:
                if not self.locker():
                    raise OSError('Windows refused the workstation lock request.')
            except OSError:
                self.logger.exception('Windows workstation lock failed')
                self.write_log('Windows blocked locking. Details are in data/errors.log.')
                self.risk_text.set('Paused')
                self.status.set('Windows blocked locking. Protection is paused.')
                messagebox.showerror('Could not lock PC', 'Windows blocked locking. Press Windows + L.', parent=self.root)
            else:
                self.risk_text.set('Lock requested')
                self.status.set('Lock requested. Protection is paused.')
            self.update_progress()

    def tick(self):
        self.timer = None
        try:
            self.check_fit()
            now = self.clock()
            if now-self.last_phone_update >= 1:
                self.last_phone_update = now
                self.update_phone_status()
            if self.active and not self.consent.get():
                self.pause()
            if self.active:
                self.advance_learning_clock(now)
                self.collector.track_current = self.mode == 'monitor'
                self.collector.poll()
                if now-self.collector.started >= SAMPLE_SECONDS:
                    frame = self.collector.finish()
                    self.record_frame(frame, self.mode == 'train' or bool(self.gate.grace_left(now)))
                if self.mode == 'train' and self.profile['training']['elapsed_seconds'] >= self.profile['training']['duration_seconds']:
                    self.finish_learning()
                elif self.mode == 'monitor':
                    if self.gate.grace_until and now >= self.gate.grace_until:
                        self.record_frame(self.collector.finish(), approved=True)
                        self.gate.grace_until = 0
                        self.begin_fit(resume=True)
                    elif now-self.last_check >= CHECK_SECONDS:
                        self.last_check = now
                        self.process(self.collector.snapshot(), now)
                if now-self.last_live_update >= .25:
                    self.last_live_update = now
                    self.update_live()
                    self.update_progress()
                    if self.mode == 'train' or self.gate.grace_left(now):
                        self.update_status()
                if now-self.last_heatmap_update >= .5:
                    self.last_heatmap_update = now
                    self.draw_heatmap()
                if now-self.last_save >= 5:
                    self.save()
        except Exception:
            self.handle_error(*sys.exc_info())
        finally:
            if not self.closed:
                self.timer = self.root.after(25, self.tick)

    def handle_error(self, error_type, error, traceback):
        self.logger.error('Application error', exc_info=(error_type, error, traceback))
        self.active = False
        self.resume_after_fit = False
        self.fit_token += 1
        self.future = None
        if self.mode == 'building':
            self.mode = 'train'
            if self.profile:
                self.profile['training']['complete'] = False
        self.gate.reset()
        self.collector.clear()
        self.update_progress()
        self.status.set('Tracking paused after an error. Your saved progress is kept.')
        self.risk_text.set('Paused')
        if not self.reporting_error and not self.closed:
            self.reporting_error = True
            try:
                messagebox.showerror('Tracking paused', 'Something went wrong, so tracking was paused.\n'
                    'Details are in data/errors.log. You can try Start again.', parent=self.root)
            finally:
                self.reporting_error = False

    def update_progress(self):
        training = self.profile.get('training', {}) if self.profile else {}
        total = training.get('duration_seconds', 300)
        elapsed = training.get('elapsed_seconds', 0)
        if self.mode == 'train' and not self.active:
            try:
                chosen = duration_seconds(self.duration_value.get(), self.duration_unit.get())
                if chosen != total:
                    total, elapsed = chosen, 0
            except ValueError:
                pass
        self.training_bar['maximum'] = total
        self.training_bar['value'] = elapsed
        self.progress.set(f'{clock_text(total-elapsed)} left' if self.mode == 'train' else
                          ('Preparing protection...' if self.mode == 'building' else 'Training complete'))
        ready = self.ai is not None and self.mode != 'train'
        self.keyboard_text.set('Ready' if ready else ('Training' if self.active else 'Training needed'))
        self.mouse_text.set('Ready' if ready else ('Training' if self.active else 'Training needed'))
        self.start_text.set(('Training...' if self.mode == 'train' else 'Protection on') if self.active else
                            ('Start training' if self.mode == 'train' else 'Start protection'))
        busy = self.future is not None
        self.start_button.configure(state='disabled' if busy or self.active else 'normal')
        editable = not self.active and not busy and self.mode == 'train'
        self.duration_input.configure(state='normal' if editable else 'disabled')
        self.unit_selector.configure(state='readonly' if editable else 'disabled')
        self.learn_button.configure(state='normal' if self.profile and not busy else 'disabled')
        from dashboard import refresh
        refresh(self)

    def update_status(self):
        left = self.gate.grace_left(self.clock())
        if self.active and left:
            self.status.set(f'Saving approved behavior. {clock_text(left)} remaining.')
            self.risk_text.set('Updating profile')
        elif self.active and self.mode == 'train':
            total = self.profile['training']
            self.status.set(f'Training: {clock_text(total["duration_seconds"]-total["elapsed_seconds"])} left. Type and use your mouse normally.')
            self.risk_text.set('Training')
        else:
            self.status.set('Watching your typing and mouse activity.' if self.active else 'Tracking is paused. Your saved behavior is kept.')
            self.risk_text.set('Protection on' if self.active else 'Paused')

    def update_live(self):
        summary = self.collector.summary()
        self.update_phone_status()
        rate = summary['typing_speed']
        self.typing_speed_text.set(f'{rate:.1f} keys/s' if rate is not None and summary['typing_active'] else '0.0 keys/s')
        band = typing_speed_band(self.profile or {})
        self.typing_reference_text.set(f'Usual speed: {band[0]:.1f} keys/s' if band else 'Train this profile to save your usual speed.')
        self.speed_text.set(f'{summary["speed"]:,.0f} px/s' if summary['speed'] is not None else '—')
        dwell = summary['held_ms'] if summary['held_ms'] is not None else summary['dwell_ms']
        self.dwell_text.set(f'{dwell:.0f} ms' if dwell is not None else '—')
        self.edge_text.set(f'{summary["edge_fraction"]:.1%}' if summary['edge_fraction'] is not None else '—')
        self.edge_detail.set('Now: '+(', '.join(summary['edges']) if summary['edges'] else 'away from edges'))

    def draw(self, threshold):
        from dashboard import draw_signal
        draw_signal(self, threshold)

    def draw_heatmap(self):
        from dashboard import draw_heatmap
        draw_heatmap(self)

    def reset_heatmap(self):
        if not self.profile or not messagebox.askyesno('Clear current activity?',
                'Clear the current activity map? Your saved pattern will be kept.', parent=self.root):
            return
        self.collector.current_heatmap.clear()
        self.save()
        self.draw_heatmap()

    def delete(self):
        self.pause()
        if self.profile and self.authenticate() and messagebox.askyesno('Delete profile?',
                'Delete this profile and its saved mouse maps?', parent=self.root):
            self.store.delete(self.profile_id)
            self.fit_token += 1
            self.future = None
            self.profile = self.profile_id = self.ai = None
            self.store.remember_selected(None)
            self.collector.reset_session()
            self.refresh_profiles()
            if self.profile_entries:
                self.load_profile(self.profile_entries[0][0])
            else:
                self.mode = 'train'
                self.gate = ThreatTimer()
                self.history = []
                self.typing_history = []
                self.last_alert_text.set('No alerts for this profile.')
                self.status.set('Profile deleted. Create a new profile to begin.')
                self.risk_text.set('Paused')
                self.update_progress()
                self.update_live()
                self.draw_heatmap()

    def update_phone_status(self):
        if self.phone.connected:
            text = 'Phone connected: '+self.phone.config.get('device_name', 'Phone')
        elif self.phone.paired:
            text = 'Phone paired. Open the phone app and tap Listen.'
        elif self.phone.enabled:
            text = 'Waiting for your phone to pair.'
        else:
            text = 'Phone alerts are off.'
        self.phone_status.set(text)
        self.phone_stop_button.configure(state='normal' if self.phone.enabled else 'disabled')
        self.phone_test_button.configure(state='normal' if self.phone.paired else 'disabled')

    def pair_phone(self):
        self.pause()
        if not self.profile:
            messagebox.showinfo('Choose a profile', 'Create or select a profile first.', parent=self.root)
            return
        authenticated = self.authenticate()
        if not authenticated:
            if authenticated is False:
                messagebox.showerror('Incorrect password', 'That password is not correct. Please try again.', parent=self.root)
            return
        try:
            from phone_ui import PairingWindow
            self.phone.begin_pairing()
            if self.phone_window and self.phone_window.winfo_exists():
                self.phone_window.close()
            self.phone_window = PairingWindow(self.root, self.phone)
        except (OSError, ImportError, ValueError) as error:
            self.logger.exception('Phone pairing failed')
            messagebox.showerror('Could not pair phone', 'Could not start the phone connection.\n'+str(error), parent=self.root)
        self.update_phone_status()

    def stop_phone(self):
        if not self.authenticate():
            return
        self.phone.close(disable=True)
        if self.phone_window and self.phone_window.winfo_exists():
            self.phone_window.close()
        self.update_phone_status()

    def test_phone(self):
        if not self.phone.paired:
            return
        self.pause()
        from phone_ui import ask_with_phone
        answer, source = ask_with_phone(self.root, self.phone, 'This is a test alert.', kind='test')
        message = f'Your phone answered {"Yes" if answer else "No"}.' if source == 'phone' else 'You answered on this PC.'
        messagebox.showinfo('Phone test', message, parent=self.root)

    def close(self):
        if self.closed:
            return
        try:
            self.pause()
        except Exception:
            self.logger.exception('Could not save while closing')
        self.closed = True
        self.phone.close()
        if self.phone_window and self.phone_window.winfo_exists():
            self.phone_window.close()
        if self.timer is not None:
            self.root.after_cancel(self.timer)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.logger.removeHandler(self.error_handler)
        self.error_handler.close()
        self.root.destroy()


if __name__ == '__main__':
    if os.name != 'nt':
        raise SystemExit('This program requires Windows.')
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()
    DATA.mkdir(exist_ok=True)
    with (DATA/'fatal-errors.log').open('a', encoding='utf-8') as fatal_log:
        faulthandler.enable(file=fatal_log)
        root = tk.Tk()
        App(root)
        root.mainloop()
        faulthandler.disable()
