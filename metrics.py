"""Windows activity measurements; only window summaries and heat-map bins are kept."""
import ctypes
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
import math
import hashlib
import json
import statistics
import time

EDGE_MARGIN = 20
HEATMAP_COLUMNS = 48
HEATMAP_ROWS = 27
# Windows reports both generic and left/right modifier states. Count physical keys once.
KEY_CODES = tuple(key for key in range(8, 255) if key not in (16, 17, 18))
MODIFIER_CODES = frozenset((16, 17, 18, 91, 92, 160, 161, 162, 163, 164, 165))
TYPING_PAUSE_SECONDS = 1.5


def mean(values):
    return statistics.mean(values) if values else 0.0


def vector(kind, samples):
    if kind == 'keyboard':
        holds, gaps = samples
        if len(holds) < 2 or len(gaps) < 2:
            return None
        return [mean(holds), mean(gaps), statistics.pstdev(gaps)]
    speeds, turns = samples[:2]
    if len(speeds) < 4:
        return None
    average = samples[3] if len(samples) > 3 and samples[3] is not None else mean(speeds)
    result = [average, statistics.pstdev(speeds), mean(turns)]
    if len(samples) > 2:
        result.append(samples[2] if samples[2] is not None else 0.0)
    return result


@dataclass(frozen=True)
class ScreenLayout:
    """Monitor rectangles in physical desktop pixels, including negative coordinates."""
    monitors: tuple

    def __post_init__(self):
        if (not self.monitors or any(len(rect) != 4 or any(
                not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect) for rect in self.monitors)
                or any(r <= l or b <= t for l, t, r, b in self.monitors)):
            raise ValueError('Screen rectangles must have a positive size')

    @property
    def bounds(self):
        return (min(m[0] for m in self.monitors), min(m[1] for m in self.monitors),
                max(m[2] for m in self.monitors), max(m[3] for m in self.monitors))

    @property
    def identifier(self):
        return hashlib.sha256(json.dumps(self.monitors).encode()).hexdigest()[:24]

    def monitor_at(self, x, y):
        return next((m for m in self.monitors if m[0] <= x < m[2] and m[1] <= y < m[3]), None)

    def edges_at(self, x, y, margin=EDGE_MARGIN):
        monitor = self.monitor_at(x, y)
        if monitor is None:
            return ()
        left, top, right, bottom = monitor
        return tuple(name for name, distance in (
            ('left', x-left), ('right', right-1-x),
            ('top', y-top), ('bottom', bottom-1-y)) if distance <= margin)


def screen_layout(user):
    rectangles = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR,
                                      wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def visit(monitor, context, rect, data):
        r = rect.contents
        rectangles.append((r.left, r.top, r.right, r.bottom))
        return True

    callback = callback_type(visit)
    user.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                         callback_type, wintypes.LPARAM]
    user.EnumDisplayMonitors.restype = wintypes.BOOL
    if not user.EnumDisplayMonitors(None, None, callback, 0) or not rectangles:
        left, top = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
        width, height = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
        rectangles = [(left, top, left+width, top+height)]
    return ScreenLayout(tuple(sorted(rectangles)))


class MouseHeatmap:
    """Coarse time-weighted occupancy, with no stored path or individual coordinates."""
    def __init__(self, layout, columns=HEATMAP_COLUMNS, rows=HEATMAP_ROWS):
        self.layout = layout
        self.columns, self.rows = columns, rows
        self.clear()

    def clear(self):
        self.cells = [[0.0]*self.columns for _ in range(self.rows)]
        self.samples = 0
        self.seconds = 0.0

    def add(self, x, y, seconds):
        if self.layout.monitor_at(x, y) is None or seconds <= 0:
            return
        left, top, right, bottom = self.layout.bounds
        column = min(self.columns-1, int((x-left)*self.columns/(right-left)))
        row = min(self.rows-1, int((y-top)*self.rows/(bottom-top)))
        self.cells[row][column] += seconds
        self.samples += 1
        self.seconds += seconds

    def to_dict(self):
        return {'monitors': self.layout.monitors, 'columns': self.columns, 'rows': self.rows,
                'cells': [row[:] for row in self.cells], 'samples': self.samples, 'seconds': self.seconds}

    @classmethod
    def from_dict(cls, data):
        layout = ScreenLayout(tuple(tuple(rect) for rect in data['monitors']))
        columns, rows = data['columns'], data['rows']
        if columns != HEATMAP_COLUMNS or rows != HEATMAP_ROWS:
            raise ValueError('Unsupported heat-map grid')
        cells = data['cells']
        if len(cells) != rows or any(len(row) != columns for row in cells):
            raise ValueError('Invalid heat-map size')
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
               for row in cells for v in row):
            raise ValueError('Invalid heat-map values')
        result = cls(layout, columns, rows)
        result.cells = [row[:] for row in cells]
        result.seconds = sum(map(sum, result.cells))
        result.samples = max(0, int(data.get('samples', 0)))
        return result

    def merge(self, other):
        if (self.layout, self.columns, self.rows) != (other.layout, other.columns, other.rows):
            raise ValueError('Cannot combine different screen layouts')
        for row in range(self.rows):
            for col in range(self.columns):
                self.cells[row][col] += other.cells[row][col]
        self.samples += other.samples
        self.seconds += other.seconds


class Collector:
    """Poll input only while the app is active. Key identifiers never leave this class."""
    def __init__(self, user=None, clock=None, layout_provider=None):
        self.user = user if user is not None else ctypes.windll.user32
        self.clock = clock or time.monotonic
        self.layout_provider = layout_provider or (lambda: screen_layout(self.user))
        self.layout = self.layout_provider()
        self.heatmap = MouseHeatmap(self.layout)
        self.heatmaps = {self.layout.identifier: self.heatmap}
        self.current_maps = {}
        self.track_current = False
        self.layout_checked = self.clock()
        self.event_serial = 0
        self.clear()

    def clear(self, preserve_keys=False):
        if not preserve_keys:
            self.down = {}
            self.press_ids = {}
            self.ignored_down = set()
            self.prime_keys = True
            self.last_key = None
            self.last_typing = None
            self.last_poll = None
            self.rate_started = self.clock()
            self.last_hold_ms = None
            self.recent = {kind: deque(maxlen=1200) for kind in ('holds', 'gaps', 'speeds', 'turns', 'positions', 'bursts', 'presses')}
            self.motion = deque(maxlen=100)
            self.last_activity = None
            self.current_position = None
        self.previous = None
        self.direction = None
        self.current_edges = ()
        self.holds, self.gaps, self.speeds, self.turns = [], [], [], []
        self.key_hold_samples = []
        self.window_presses = []
        self.mouse_peak_speed = 0.0
        self.moving_distance = self.moving_seconds = 0.0
        self.position_seconds = self.edge_seconds = 0.0
        self.edge_times = dict.fromkeys(('left', 'right', 'top', 'bottom'), 0.0)
        self.window_map = MouseHeatmap(self.layout)
        self.started = self.clock()

    def reset_session(self):
        self.clear()
        self.heatmap = MouseHeatmap(self.layout)
        self.heatmaps = {self.layout.identifier: self.heatmap}
        self.current_maps = {}

    def restore_heatmaps(self, records):
        maps = {}
        for key, data in records.items():
            heatmap = MouseHeatmap.from_dict(data)
            if key != heatmap.layout.identifier:
                raise ValueError('Invalid saved screen layout')
            maps[key] = heatmap
        self.heatmaps = maps
        self.heatmap = self.heatmaps.setdefault(self.layout.identifier, MouseHeatmap(self.layout))

    def saved_heatmaps(self):
        return {key: heatmap.to_dict() for key, heatmap in self.heatmaps.items()}

    def restore_current_maps(self, records):
        self.current_maps = {key: MouseHeatmap.from_dict(value) for key, value in records.items()}

    def saved_current_maps(self):
        return {key: value.to_dict() for key, value in self.current_maps.items()}

    @property
    def current_heatmap(self):
        return self.current_maps.setdefault(self.layout.identifier, MouseHeatmap(self.layout))

    def reset_mouse_detection(self):
        """Discard speed bursts from a period in which mouse checks were suspended."""
        self.motion.clear()
        self.recent['bursts'].clear()
        self.mouse_peak_speed = 0.0
        self.previous = self.direction = None

    def typing_active(self):
        return (self.last_typing is not None and self.clock()-self.last_typing <= TYPING_PAUSE_SECONDS
                or any(key not in MODIFIER_CODES for key in self.down))

    def typing_rate(self, seconds=2, window=False):
        now = self.clock()
        start = max(self.rate_started, self.started) if window else self.rate_started
        elapsed = min(seconds, max(0, now-start))
        if elapsed < 1:
            return None
        presses = self.window_presses if window else [event[0] for event in self.recent['presses']]
        count = sum(now-elapsed < stamp <= now for stamp in presses)
        return count/elapsed if count >= 2 else None

    def poll(self):
        now = self.clock()
        if now-self.layout_checked >= 1:
            layout = self.layout_provider()
            if layout != self.layout:
                self.layout = layout
                self.heatmap = self.heatmaps.setdefault(layout.identifier, MouseHeatmap(layout))
                self.clear()
            self.layout_checked = now
        if self.last_poll is not None and now-self.last_poll > .2:
            self.recent['presses'].clear()
            self.window_presses.clear()
            self.rate_started, self.last_typing = now, None
        self.last_poll = now
        for key in KEY_CODES:
            pressed = bool(self.user.GetAsyncKeyState(key) & 0x8000)
            if self.prime_keys and pressed:
                self.ignored_down.add(key)
            if key in self.ignored_down:
                if not pressed:
                    self.ignored_down.remove(key)
                continue
            if pressed and key not in self.down:
                self.down[key] = now
                self.event_serial += 1
                self.press_ids[key] = self.event_serial
                self.last_activity = now
                if key not in MODIFIER_CODES:
                    self.window_presses.append(now)
                    self.recent['presses'].append((now,))
                    self.last_typing = now
                    if self.last_key is not None and .02 < now-self.last_key < 2:
                        self.gaps.append((now-self.last_key)*1000)
                        self.recent['gaps'].append((now, self.gaps[-1]))
                    self.last_key = now
            elif not pressed and key in self.down:
                held = now-self.down.pop(key)
                identifier = self.press_ids.pop(key, 0)
                if held > 0:
                    self.last_hold_ms = held*1000
                    self.holds.append(held*1000)
                    eligible = key not in MODIFIER_CODES
                    self.recent['holds'].append((now, held*1000, identifier, eligible))
                    if eligible:
                        self.key_hold_samples.append(held*1000)
                        self.last_typing = now
                    self.last_activity = now
        self.prime_keys = False
        point = wintypes.POINT()
        if not self.user.GetCursorPos(ctypes.byref(point)):
            self.current_position = None
            self.previous = None
            self.direction = None
            self.current_edges = ()
            self.motion.clear()
            return
        valid = self.layout.monitor_at(point.x, point.y) is not None
        self.current_position = (point.x, point.y) if valid else None
        dt = now-self.previous[2] if self.previous else 0
        seconds = dt if 0 < dt < .2 else 0
        self.current_edges = self.layout.edges_at(point.x, point.y)
        if valid and seconds:
            self.heatmap.add(point.x, point.y, seconds)
            if self.track_current:
                self.current_heatmap.add(point.x, point.y, seconds)
            self.window_map.add(point.x, point.y, seconds)
            self.recent['positions'].append((now, point.x, point.y, seconds, bool(self.current_edges)))
            self.position_seconds += seconds
            if self.current_edges:
                self.edge_seconds += seconds
                for edge in self.current_edges:
                    self.edge_times[edge] += seconds
        if valid and self.previous and seconds:
            x, y, _ = self.previous
            dx, dy = point.x-x, point.y-y
            distance = math.hypot(dx, dy)
            self.motion.append((now, distance if distance > 1 else 0, seconds))
            while self.motion and self.motion[0][0] <= now-.1:
                self.motion.popleft()
            covered = travelled = 0.0
            for end, amount, duration in self.motion:
                overlap = min(duration, max(0, end-max(end-duration, now-.1)))
                covered += overlap
                travelled += amount*overlap/duration
            if covered >= .095 and len(self.motion) >= 3:
                burst_speed = travelled/covered
                self.mouse_peak_speed = max(self.mouse_peak_speed, burst_speed)
                self.recent['bursts'].append((now, burst_speed))
            if distance > 1:
                self.speeds.append(distance/seconds)
                self.recent['speeds'].append((now, distance/seconds, distance, seconds))
                self.last_activity = now
                self.moving_distance += distance
                self.moving_seconds += seconds
                direction = math.atan2(dy, dx)
                if self.direction is not None:
                    self.turns.append(abs((direction-self.direction+math.pi) % (2*math.pi)-math.pi))
                    self.recent['turns'].append((now, self.turns[-1]))
                self.direction = direction
            else:
                self.direction = None
        else:
            self.direction = None
            self.motion.clear()
        self.previous = (point.x, point.y, now) if valid else None
        for events in self.recent.values():
            while events and events[0][0] < now-3:
                events.popleft()

    def summary(self):
        return {
            'speed': self.moving_distance/self.moving_seconds if self.moving_seconds else None,
            'dwell_ms': statistics.mean(self.holds) if self.holds else self.last_hold_ms,
            'edge_fraction': self.edge_seconds/self.position_seconds if self.position_seconds else None,
            'edges': self.current_edges,
            'released_keys': len(self.holds),
            'held_ms': max(((self.clock()-start)*1000 for start in self.down.values()), default=None),
            'typing_speed': self.typing_rate(),
            'typing_active': self.typing_active(),
        }

    def finish(self):
        # Keep presses that span a window boundary until their real release.
        summary = self.summary()
        result = {
            'keyboard': vector('keyboard', (self.holds, self.gaps)),
            'mouse': vector('mouse', (self.speeds, self.turns,
                                      summary['edge_fraction'], summary['speed'])),
            'heatmap': self.window_map.to_dict(),
            'key_hold_samples': self.key_hold_samples[:],
            'mouse_peak_speed': self.mouse_peak_speed,
            'typing_speed': self.typing_rate(window=True),
        }
        self.clear(preserve_keys=True)
        return result

    def snapshot(self, seconds=2):
        cutoff = self.clock()-seconds
        events = {kind: [event for event in values if event[0] >= cutoff]
                  for kind, values in self.recent.items()}
        positions = MouseHeatmap(self.layout)
        total = edge_time = 0
        for _, x, y, dt, at_edge in events['positions']:
            positions.add(x, y, dt)
            total += dt
            edge_time += dt*at_edge
        moving_time = sum(event[3] for event in events['speeds'])
        speed = sum(event[2] for event in events['speeds'])/moving_time if moving_time else None
        latest_positions = [event for event in events['positions'] if event[0] >= self.clock()-.5]
        mouse_moving = bool(latest_positions) and (
            max(v[1] for v in latest_positions)-min(v[1] for v in latest_positions) > 3
            or max(v[2] for v in latest_positions)-min(v[2] for v in latest_positions) > 3)
        return {
            'keyboard': vector('keyboard', ([v[1] for v in events['holds']], [v[1] for v in events['gaps']])),
            'mouse': vector('mouse', ([v[1] for v in events['speeds']], [v[1] for v in events['turns']],
                                      edge_time/total if total else 0, speed)),
            'heatmap': positions.to_dict(),
            'key_hold_samples': [v[1] for v in events['holds'] if v[3]],
            'dwell_events': [(v[2], v[1]) for v in events['holds'] if v[3]],
            'held_durations': [(self.press_ids[key], (self.clock()-start)*1000)
                               for key, start in self.down.items()
                               if key not in MODIFIER_CODES and key in self.press_ids],
            'mouse_peak_speed': max((v[1] for v in events['bursts']), default=0.0),
            'cursor_position': self.current_position,
            'mouse_moving': mouse_moving,
            'typing_speed': self.typing_rate(seconds),
            'typing_active': self.typing_active(),
            'active': self.last_activity is not None and self.clock()-self.last_activity <= .75,
        }
