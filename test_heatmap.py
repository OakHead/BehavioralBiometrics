import unittest

from detection import MODE_SECONDS, ThreatTimer, alert_delay, dwell_limits, DwellWatch
from heatmap import HeatField, SpatialWatch, heat_rgb, raster_ppm
from metrics import MouseHeatmap, ScreenLayout


class HeatmapRulesTests(unittest.TestCase):
    def setUp(self):
        self.layout = ScreenLayout(((0, 0, 1000, 1000),))
        self.hot = ((24+.5)*1000/48, (13+.5)*1000/27)
        self.recorded = MouseHeatmap(self.layout)
        self.recorded.add(*self.hot, 100)
        self.field = HeatField(self.recorded)

    def test_mode_delays_are_exactly_the_requested_values(self):
        self.assertEqual(MODE_SECONDS, {'Low': 2.5, 'Balanced': 5, 'High': 7.5})
        for mode, delay in MODE_SECONDS.items():
            timer = ThreatTimer()
            for step in range(int(delay*2)):
                self.assertFalse(timer.update(step*.5, True, seconds=alert_delay(mode)))
            self.assertTrue(timer.update(delay, True, seconds=alert_delay(mode)))

    def test_gaussian_heat_has_hot_center_warm_neighbors_and_empty_far_areas(self):
        near = (self.hot[0]+1000/48, self.hot[1])
        farther = (self.hot[0]+2*1000/48, self.hot[1])
        self.assertAlmostEqual(self.field.sample(*self.hot), 1)
        self.assertGreater(self.field.sample(*near), self.field.sample(*farther))
        self.assertGreater(self.field.sample(*farther), 0)
        self.assertEqual(self.field.sample(900, 900), 0)
        red, green, blue = heat_rgb(.75)
        self.assertGreater(red, 220)
        self.assertGreater(green, 200)
        self.assertLess(blue, 100)

    def test_red_idle_allowance_is_five_times_the_selected_mode(self):
        for mode, base in MODE_SECONDS.items():
            with self.subTest(mode=mode):
                watcher = SpatialWatch()
                for step in range(int(base*5*2)):
                    self.assertIsNone(watcher.update(step*.5, self.hot, self.field, base))
                reason = watcher.update(base*5, self.hot, self.field, base)
                self.assertEqual(reason['kind'], 'cursor_idle')
                self.assertAlmostEqual(reason['limit'], base*5)

    def test_moving_across_empty_cells_does_not_reset_the_outside_timer(self):
        watcher = SpatialWatch()
        for step in range(10):
            self.assertIsNone(watcher.update(step*.5, (800+step*5, 900), self.field, 5))
        reason = watcher.update(5, (900, 900), self.field, 5)
        self.assertEqual(reason['kind'], 'mouse_area')
        self.assertEqual(reason['limit'], 5)

    def test_returning_to_recorded_space_resets_outside_time(self):
        watcher = SpatialWatch()
        for step in range(8):
            watcher.update(step*.5, (900, 900), self.field, 5)
        self.assertIsNone(watcher.update(4, self.hot, self.field, 5))
        self.assertIsNone(watcher.update(4.5, (900, 900), self.field, 5))
        self.assertEqual(watcher.outside_since, 4.5)

    def test_movement_returning_to_same_position_still_counts_as_movement(self):
        watcher = SpatialWatch()
        for step in range(80):
            self.assertIsNone(watcher.update(step*.5, self.hot, self.field, 5, moving=True))

    def test_long_sampling_interruption_starts_fresh_timers(self):
        watcher = SpatialWatch()
        watcher.update(0, (900, 900), self.field, 5)
        self.assertIsNone(watcher.update(10, (900, 900), self.field, 5))
        self.assertEqual(watcher.outside_since, 10)

    def test_dwell_boundary_is_strictly_above_double_maximum(self):
        limits = dwell_limits({'key_dwell_max_ms': 500})
        watch = DwellWatch()
        self.assertIsNone(watch.observe(0, [], [(1, 1000)], limits))
        reason = watch.observe(.5, [], [(1, 1001)], limits)
        self.assertEqual(reason['observed'], 1001)
        self.assertEqual(reason['limit'], 1000)

    def test_heatmap_raster_is_valid_binary_ppm_with_exact_pixel_count(self):
        data = raster_ppm(self.field, 64, 36)
        header = b'P6\n64 36\n255\n'
        self.assertTrue(data.startswith(header))
        self.assertEqual(len(data)-len(header), 64*36*3)


if __name__ == '__main__':
    unittest.main()
