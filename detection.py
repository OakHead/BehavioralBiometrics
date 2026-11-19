"""Time-based alert rules and comparison with approved cursor areas."""
import math
import statistics
from collections import deque

ALERT_SECONDS = 5.0
GRACE_SECONDS = 60.0
SAMPLE_SECONDS = 2.0
CHECK_SECONDS = .5
MIN_SAMPLES = 5
MAX_SAMPLES = 240
MODE_SECONDS = {'Low': 2.5, 'Balanced': 5.0, 'High': 7.5}


def alert_delay(mode):
    aliases = {'Relaxed': 'Low', 'Sensitive': 'High'}
    return MODE_SECONDS[aliases.get(mode, mode)]


def learned_mouse_limit(profile):
    limit = profile.get('mouse_speed_limit')
    if isinstance(limit, (int, float)) and math.isfinite(limit) and limit > 0:
        return float(limit)
    # Older versions saved mean/variation rather than actual peak speed.
    rows = profile.get('mouse', [])
    return max((row[0]+3*row[1] for row in rows), default=0.0)


def dwell_limits(profile, sensitivity='Balanced'):
    saved = profile.get('key_dwell_max_ms', 0)
    if saved > 0:
        maximum = float(round(saved))
        return maximum, maximum*2
    samples = profile.get('key_hold_samples') or [row[0] for row in profile.get('keyboard', [])]
    if not samples:
        return None
    maximum = round(max(max(samples), profile.get('key_hold_approved_max', 0)))
    return float(maximum), float(maximum)*2


def dwell_reason(observed, typical, limit):
    return {'kind': 'key_dwell', 'observed': float(observed), 'limit': float(limit),
            'typical': float(typical),
            'text': f'Long key hold: {observed:.0f} ms.'}


def speed_reason(observed, limit):
    return {'kind': 'mouse_speed', 'observed': float(observed), 'limit': float(limit),
            'text': f'Mouse moved too fast: {observed:,.0f} px/s.'}


def typing_speed_band(profile):
    """A per-profile speed range, with compatibility for older gap-only profiles."""
    samples = profile.get('typing_speed_samples') or [1000/row[1] for row in profile.get('keyboard', []) if row[1] > 0]
    if not samples:
        return None
    samples = sorted(samples)
    center = statistics.median(samples)
    spread = 1.4826*statistics.median(abs(value-center) for value in samples)
    low_sample = samples[int((len(samples)-1)*.1)]
    high_sample = samples[math.ceil((len(samples)-1)*.9)]
    low = max(.25, min(center*.5, low_sample-2*spread))
    high = max(center*1.5, center+1.5, high_sample+2*spread)
    return center, low, high


def assess_typing_speed(profile, observed):
    band = typing_speed_band(profile)
    if band is None or observed is None or observed <= 0:
        return None
    center, low, high = band
    distance = ((center-observed)/max(.1, center-low) if observed < center
                else (observed-center)/max(.1, high-center))
    risk = min(.98, .25+.40*distance)
    direction = 'faster' if observed > center else 'slower'
    reason = {'kind': 'typing_speed', 'observed': float(observed), 'reference': float(center),
              'low': float(low), 'high': float(high),
              'text': f'Typing is {direction} than your saved pattern ({observed:.1f} keys/s).'}
    return risk, reason


class DwellWatch:
    """Alert immediately above twice the saved maximum, including before release."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.pending = None
        self.seen = set()
        self.seen_order = deque()
        self.last_check = None

    def observe(self, now, released, held, limits):
        if limits is None:
            return None
        typical, limit = limits
        self.last_check = now
        for identifier, duration in released:
            if identifier in self.seen:
                continue
            self.seen.add(identifier)
            self.seen_order.append(identifier)
            if len(self.seen_order) > 256:
                self.seen.discard(self.seen_order.popleft())
            if math.floor(duration+1e-6) > limit:
                return dwell_reason(math.floor(duration+1e-6), typical, limit)
        for identifier, duration in held:
            if math.floor(duration+1e-6) > limit:
                return dwell_reason(math.floor(duration+1e-6), typical, limit)
        return None

    def flag(self, now, identifier, duration, typical, limit):
        if self.pending is None:
            self.pending = {'since': now, 'identifier': identifier, 'duration': duration}
        else:
            self.pending['duration'] = max(self.pending['duration'], duration)


def duration_seconds(value, unit):
    try:
        seconds = float(value)*(60 if unit == 'minutes' else 1)
    except (TypeError, ValueError) as exc:
        raise ValueError('Choose a duration from 10 seconds to 60 minutes.') from exc
    if not math.isfinite(seconds) or not 10 <= seconds <= 3600:
        raise ValueError('Choose a duration from 10 seconds to 60 minutes.')
    return seconds


def clock_text(seconds):
    seconds = max(0, math.ceil(seconds))
    return f'{seconds//60:02d}:{seconds%60:02d}'


class ThreatTimer:
    """Only fresh, uninterrupted abnormal checks count toward an alert."""
    def __init__(self):
        self.grace_until = 0.0
        self.reset()

    def reset(self):
        self.since = None
        self.last_check = None

    def grant_grace(self, now):
        self.reset()
        self.grace_until = now+GRACE_SECONDS

    def grace_left(self, now):
        return max(0, self.grace_until-now)

    def update(self, now, unusual, active=True, seconds=ALERT_SECONDS):
        if self.grace_left(now) or not active or not unusual:
            self.reset()
            return False
        if self.last_check is None or now-self.last_check > 1.5 or now < self.last_check:
            self.since = now
        self.last_check = now
        return now-self.since >= seconds

    def different_for(self, now):
        return max(0, now-self.since) if self.since is not None else 0


class PositionModel:
    """Compare recent occupancy with owner-approved heat-map cells, allowing nearby bins."""
    def __init__(self, heatmap):
        self.layout = heatmap.layout
        self.columns, self.rows = heatmap.columns, heatmap.rows
        self.density = []
        for row in range(self.rows):
            values = []
            for col in range(self.columns):
                value = sum(heatmap.cells[r][c]/(1+abs(r-row)+abs(c-col))
                            for r in range(max(0, row-2), min(self.rows, row+3))
                            for c in range(max(0, col-2), min(self.columns, col+3)))
                values.append(value)
            self.density.append(values)
        self.maximum = max((max(row) for row in self.density), default=0)

    def assess(self, recent):
        if not self.maximum or recent.layout != self.layout or not recent.seconds:
            return None
        novelty = sum(value*(1-min(1, math.log1p(self.density[r][c])/math.log1p(self.maximum)))
                      for r, row in enumerate(recent.cells) for c, value in enumerate(row) if value)
        return .40+.40*novelty/recent.seconds
