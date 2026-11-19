"""The same smoothed recorded heat is used for both drawing and mouse-area rules."""
import math

STOPS = ((0, (13, 22, 38)), (.05, (35, 70, 215)), (.25, (20, 200, 220)),
         (.5, (65, 215, 80)), (.75, (255, 225, 55)), (1, (255, 154, 54)))


def heat_rgb(value):
    value = min(1, max(0, value))
    for (low, start), (high, end) in zip(STOPS, STOPS[1:]):
        if value <= high:
            part = (value-low)/(high-low)
            return tuple(round(a+(b-a)*part) for a, b in zip(start, end))
    return STOPS[-1][1]


COLORS = tuple(heat_rgb(index/255) for index in range(256))


def raster_ppm(field, width, height):
    left, top, right, bottom = field.layout.bounds
    pixels = bytearray()
    for row in range(height):
        y = top+(row+.5)*(bottom-top)/height
        for column in range(width):
            x = left+(column+.5)*(right-left)/width
            if field.layout.monitor_at(x, y) is None:
                pixels.extend((19, 30, 48))
            else:
                pixels.extend(COLORS[round(min(1, max(0, field.sample(x, y)))*255)])
    return f'P6\n{width} {height}\n255\n'.encode()+bytes(pixels)


class HeatField:
    def __init__(self, heatmap):
        self.layout = heatmap.layout
        self.columns, self.rows = heatmap.columns, heatmap.rows
        radius, sigma = 3, 1.25
        kernel = [(dx, dy, math.exp(-(dx*dx+dy*dy)/(2*sigma*sigma)))
                  for dy in range(-radius, radius+1) for dx in range(-radius, radius+1)]
        density = [[0.0]*self.columns for _ in range(self.rows)]
        for row, values in enumerate(heatmap.cells):
            for column, value in enumerate(values):
                if value <= 0:
                    continue
                for dx, dy, weight in kernel:
                    x, y = column+dx, row+dy
                    if 0 <= x < self.columns and 0 <= y < self.rows:
                        density[y][x] += value*weight
        maximum = max((max(row) for row in density), default=0)
        self.values = [[math.sqrt(value/maximum) if maximum and value/maximum >= .0004 else 0
                        for value in row] for row in density]

    def sample(self, x, y):
        if self.layout.monitor_at(x, y) is None:
            return 0.0
        left, top, right, bottom = self.layout.bounds
        u = min(self.columns-1, max(0, (x-left)/(right-left)*self.columns-.5))
        v = min(self.rows-1, max(0, (y-top)/(bottom-top)*self.rows-.5))
        x0, y0 = int(u), int(v)
        x1, y1 = min(x0+1, self.columns-1), min(y0+1, self.rows-1)
        fx, fy = u-x0, v-y0
        return ((self.values[y0][x0]*(1-fx)+self.values[y0][x1]*fx)*(1-fy)
                +(self.values[y1][x0]*(1-fx)+self.values[y1][x1]*fx)*fy)


class SpatialWatch:
    def __init__(self):
        self.reset()

    def reset(self):
        self.outside_since = self.idle_since = self.last_check = None
        self.anchor = None
        self.layout_id = None
        self.info = None

    def update(self, now, position, field, base_seconds, moving=False):
        if position is None:
            self.reset()
            return None
        layout_id = field.layout.identifier
        if (self.last_check is None or now-self.last_check > 1.5
                or self.layout_id != layout_id or now < self.last_check):
            self.reset()
            self.anchor = position
            self.idle_since = now
            self.layout_id = layout_id
        self.last_check = now
        heat = field.sample(*position)
        outside = heat < .02
        if outside:
            if self.outside_since is None:
                self.outside_since = now
        else:
            self.outside_since = None
        if moving or self.anchor is None or math.dist(position, self.anchor) > 3:
            self.anchor = position
            self.idle_since = now
        idle_elapsed = now-self.idle_since
        idle_limit = base_seconds*(1+4*heat)
        outside_elapsed = now-self.outside_since if self.outside_since is not None else 0
        self.info = {'heat': heat, 'idle_elapsed': idle_elapsed, 'idle_limit': idle_limit,
                     'outside_elapsed': outside_elapsed, 'outside': outside}
        if self.outside_since is not None and outside_elapsed >= base_seconds:
            return {'kind': 'mouse_area', 'observed': outside_elapsed, 'limit': base_seconds,
                    'text': f'Cursor stayed outside your recorded mouse areas for {outside_elapsed:.1f}s.'}
        if idle_elapsed >= idle_limit:
            return {'kind': 'cursor_idle', 'observed': idle_elapsed, 'limit': idle_limit, 'heat': heat,
                    'text': f'Cursor stayed still for {idle_elapsed:.1f}s.'}
        return None
