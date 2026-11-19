"""Deterministic input traces; no real keyboard or mouse activity is recorded."""
import ctypes
from ctypes import wintypes
import unittest

from metrics import Collector, MouseHeatmap, ScreenLayout, vector


class FakeInput:
    def __init__(self):
        self.keys = set()
        self.position = (500, 500)
        self.cursor_ok = True

    def GetAsyncKeyState(self, key):
        return 0x8000 if key in self.keys else 0

    def GetCursorPos(self, pointer):
        point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
        point.x, point.y = self.position
        return self.cursor_ok


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.user = FakeInput()
        self.layout = ScreenLayout(((0, 0, 1000, 1000),))
        self.collector = Collector(self.user, lambda: self.now, lambda: self.layout)
        self.collector.poll()

    def poll(self, seconds=.025, keys=None, position=None):
        self.now += seconds
        if keys is not None:
            self.user.keys = set(keys)
        if position is not None:
            self.user.position = position
        self.collector.poll()

    def test_speed_is_distance_over_time_not_unweighted_poll_mean(self):
        self.poll(.1, position=(510, 500))
        self.poll(.05, position=(520, 500))
        self.assertAlmostEqual(self.collector.summary()['speed'], 20/.15)

    def test_current_hold_is_visible_before_release_and_has_an_individual_event(self):
        self.poll(keys=[65])
        self.poll(1, keys=[65])
        self.assertAlmostEqual(self.collector.summary()['held_ms'], 1000)
        snapshot = self.collector.snapshot()
        self.assertAlmostEqual(snapshot['held_durations'][0][1], 1000)
        self.poll(.025, keys=[])
        snapshot = self.collector.snapshot()
        self.assertIsNone(snapshot['keyboard'])
        self.assertAlmostEqual(snapshot['dwell_events'][0][1], 1025)

    def test_peak_speed_is_measured_over_a_short_burst(self):
        for index in range(1, 6):
            self.poll(.025, position=(500+index*10, 500))
        self.assertAlmostEqual(self.collector.snapshot()['mouse_peak_speed'], 400)
        self.assertAlmostEqual(self.collector.finish()['mouse_peak_speed'], 400)

    def test_tiny_poll_interval_does_not_create_an_instantaneous_speed_spike(self):
        self.poll(.001, position=(510, 500))
        for _ in range(4):
            self.poll(.025)
        self.assertLess(self.collector.snapshot()['mouse_peak_speed'], 200)

    def test_individual_completed_holds_are_saved_for_learning(self):
        self.poll(keys=[65])
        self.poll(.1, keys=[])
        frame = self.collector.finish()
        self.assertEqual(len(frame['key_hold_samples']), 1)
        self.assertAlmostEqual(frame['key_hold_samples'][0], 100)


    def test_stationary_time_is_heatmapped_but_not_moving_speed(self):
        for _ in range(4):
            self.poll(.1)
        self.assertIsNone(self.collector.summary()['speed'])
        self.assertAlmostEqual(self.collector.heatmap.seconds, .4)
        self.assertAlmostEqual(sum(map(sum, self.collector.heatmap.cells)), .4)

    def test_dwell_uses_first_press_and_real_release(self):
        self.poll(keys=[65])
        self.poll(.1, keys=[65])
        self.poll(.05, keys=[])
        self.assertAlmostEqual(self.collector.summary()['dwell_ms'], 150)
        self.assertEqual(self.collector.summary()['released_keys'], 1)

    def test_dwell_longer_than_two_seconds_is_measured(self):
        self.poll(keys=[65])
        self.poll(3, keys=[])
        self.assertAlmostEqual(self.collector.summary()['dwell_ms'], 3000)

    def test_key_spanning_windows_is_not_restarted(self):
        self.poll(keys=[65])
        self.poll(.1, keys=[65])
        self.collector.finish()
        self.poll(.1, keys=[])
        self.assertAlmostEqual(self.collector.summary()['dwell_ms'], 200)

    def test_keys_already_down_on_resume_are_ignored_until_released(self):
        self.collector.clear()
        self.poll(keys=[65])
        self.poll(.1, keys=[])
        self.assertEqual(self.collector.holds, [])
        self.poll(keys=[65])
        self.poll(.1, keys=[])
        self.assertAlmostEqual(self.collector.summary()['dwell_ms'], 100)

    def test_generic_modifiers_do_not_duplicate_physical_shift(self):
        self.poll(keys=[16, 160])
        self.poll(.1, keys=[])
        self.assertEqual(len(self.collector.holds), 1)

    def test_corner_counts_once_in_total_edge_time(self):
        self.poll(.1, position=(0, 0))
        self.poll(.1, position=(500, 500))
        summary = self.collector.summary()
        self.assertAlmostEqual(summary['edge_fraction'], .5)
        self.assertAlmostEqual(self.collector.edge_times['left'], .1)
        self.assertAlmostEqual(self.collector.edge_times['top'], .1)
        self.assertEqual(summary['edges'], ())

    def test_sleep_or_polling_stall_does_not_create_speed_or_heat(self):
        self.poll(10, position=(900, 900))
        self.assertIsNone(self.collector.summary()['speed'])
        self.assertEqual(self.collector.heatmap.seconds, 0)

    def test_failed_position_read_is_not_a_zero_coordinate_sample(self):
        self.user.cursor_ok = False
        self.poll(.1)
        self.assertEqual(self.collector.heatmap.seconds, 0)
        self.assertIsNone(self.collector.previous)

    def test_window_finishes_without_erasing_session_heatmap(self):
        self.poll(.1, position=(0, 0))
        self.collector.finish()
        self.assertAlmostEqual(self.collector.heatmap.seconds, .1)
        self.assertIsNone(self.collector.summary()['edge_fraction'])
        self.collector.reset_session()
        self.assertEqual(self.collector.heatmap.samples, 0)

    def test_display_change_resets_heatmap_instead_of_mixing_coordinates(self):
        self.poll(.1)
        self.layout = ScreenLayout(((-1000, 0, 0, 1000), (0, 0, 1000, 1000)))
        self.poll(1)
        self.assertEqual(self.collector.heatmap.layout, self.layout)
        self.assertEqual(self.collector.heatmap.samples, 0)

    def test_saved_map_for_an_old_display_layout_returns_when_the_layout_returns(self):
        self.poll(.1)
        original = self.layout
        self.layout = ScreenLayout(((-1000, 0, 0, 1000), (0, 0, 1000, 1000)))
        self.poll(1)
        self.layout = original
        self.poll(1)
        self.assertAlmostEqual(self.collector.heatmap.seconds, .1)

    def test_active_trace_produces_four_mouse_features(self):
        for i in range(20):
            self.poll(position=(100+i*10, 100+(i % 2)*10))
        result = self.collector.finish()
        self.assertEqual(len(result['mouse']), 4)
        self.assertGreater(result['mouse'][0], 0)
        self.assertEqual(result['mouse'][3], 0)
        self.assertIsNone(result['keyboard'])


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.layout = ScreenLayout(((-1920, 0, 0, 1080), (0, -200, 2560, 1240)))

    def test_all_edges_and_negative_coordinates(self):
        self.assertEqual(self.layout.edges_at(-1920, 500), ('left',))
        self.assertEqual(self.layout.edges_at(-1, 500), ('right',))
        self.assertEqual(self.layout.edges_at(500, -200), ('top',))
        self.assertEqual(self.layout.edges_at(2559, 1239), ('right', 'bottom'))
        self.assertEqual(self.layout.edges_at(500, 500), ())
        self.assertEqual(self.layout.edges_at(-1000, -100), ())

    def test_edge_margin_boundary(self):
        self.assertIn('left', self.layout.edges_at(20, 500))
        self.assertNotIn('left', self.layout.edges_at(21, 500))

    def test_heatmap_handles_extremes_without_clipping_wrong_monitor(self):
        heatmap = MouseHeatmap(self.layout)
        heatmap.add(-1920, 0, .1)
        heatmap.add(2559, 1239, .2)
        heatmap.add(-1000, -100, 50)
        self.assertEqual(heatmap.samples, 2)
        self.assertAlmostEqual(heatmap.seconds, .3)
        self.assertAlmostEqual(heatmap.cells[-1][-1], .2)

    def test_empty_or_invalid_monitors_are_rejected(self):
        for monitors in ((), ((0, 0, 0, 10),), ((0, 20, 10, 10),)):
            with self.assertRaises(ValueError):
                ScreenLayout(monitors)

    def test_vector_uses_weighted_speed_and_edge_fraction(self):
        value = vector('mouse', ([100]*12, [.4]*6, .25, 120))
        self.assertEqual(value, [120, 0, .4, .25])

    def test_saved_heatmap_roundtrips_without_losing_time_or_negative_coordinates(self):
        import json
        heatmap = MouseHeatmap(self.layout)
        heatmap.add(-1920, 500, .2)
        heatmap.add(2559, 1239, .4)
        restored = MouseHeatmap.from_dict(json.loads(json.dumps(heatmap.to_dict())))
        self.assertEqual(restored.cells, heatmap.cells)
        self.assertEqual(restored.layout, self.layout)
        self.assertAlmostEqual(restored.seconds, .6)
        self.assertEqual(restored.samples, 2)


if __name__ == '__main__':
    unittest.main()
