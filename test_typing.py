"""Typing-rate measurement and learned ranges, independent of cursor movement."""
import unittest
from detection import assess_typing_speed, typing_speed_band
from metrics import Collector, ScreenLayout
from test_metrics import FakeInput


class TypingMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.user = FakeInput()
        self.collector = Collector(self.user, lambda: self.now, lambda: ScreenLayout(((0, 0, 1000, 1000),)))
        self.collector.poll()

    def poll(self, keys=(), seconds=.025):
        self.now += seconds
        self.user.keys = set(keys)
        self.collector.poll()

    def type_for(self, seconds, group=(65,), period=8):
        for index in range(round(seconds/.025)):
            self.poll(group if index % period < 2 else ())

    def test_five_presses_per_second_is_measured_and_saved(self):
        self.type_for(2)
        self.assertAlmostEqual(self.collector.summary()['typing_speed'], 5)
        self.assertAlmostEqual(self.collector.finish()['typing_speed'], 5)

    def test_mashing_several_keys_in_one_poll_counts_every_press(self):
        self.type_for(2, group=(65, 66, 67, 68), period=4)
        frame = self.collector.finish()
        self.assertAlmostEqual(frame['typing_speed'], 40)
        self.assertAlmostEqual(frame['keyboard'][1], 100)

    def test_rolling_speed_does_not_restart_at_summary_boundaries(self):
        self.type_for(2)
        self.collector.finish()
        self.type_for(1)
        self.assertAlmostEqual(self.collector.snapshot()['typing_speed'], 5)

    def test_shift_and_control_do_not_inflate_speed_or_pause_mouse_checks(self):
        self.type_for(2, group=(160, 162), period=4)
        self.assertIsNone(self.collector.snapshot()['typing_speed'])
        self.assertFalse(self.collector.snapshot()['typing_active'])

    def test_holding_one_key_is_not_counted_as_repeated_typing(self):
        for _ in range(80):
            self.poll((65,))
        self.assertIsNone(self.collector.snapshot()['typing_speed'])
        self.assertTrue(self.collector.snapshot()['typing_active'])
        self.assertGreater(self.collector.snapshot()['held_durations'][0][1], 1900)

    def test_typing_becomes_inactive_after_a_short_pause(self):
        self.type_for(2)
        for _ in range(64):
            self.poll()
        self.assertFalse(self.collector.snapshot()['typing_active'])

    def test_lost_cursor_read_does_not_stop_typing_measurement(self):
        self.user.cursor_ok = False
        self.type_for(2)
        self.assertAlmostEqual(self.collector.snapshot()['typing_speed'], 5)

    def test_a_polling_stall_starts_a_fresh_speed_window(self):
        self.type_for(2)
        self.poll(seconds=10)
        self.assertIsNone(self.collector.snapshot()['typing_speed'])


class TypingRangeTests(unittest.TestCase):
    def test_normal_speed_is_below_alert_level_and_faster_and_slower_are_above(self):
        profile = {'typing_speed_samples': [5]*20}
        self.assertLess(assess_typing_speed(profile, 5)[0], .65)
        self.assertGreater(assess_typing_speed(profile, 12)[0], .65)
        self.assertGreater(assess_typing_speed(profile, 1)[0], .65)
        self.assertIn('faster', assess_typing_speed(profile, 12)[1]['text'])

    def test_old_gap_only_profiles_get_an_initial_speed_range(self):
        self.assertEqual(typing_speed_band({'keyboard': [[100, 200, 30]]*10})[0], 5)

    def test_direct_speed_measurements_take_priority_over_old_gap_means(self):
        profile = {'typing_speed_samples': [8]*20, 'keyboard': [[100, 200, 30]]*10}
        self.assertEqual(typing_speed_band(profile)[0], 8)

    def test_missing_or_zero_activity_does_not_invent_a_speed_anomaly(self):
        self.assertIsNone(assess_typing_speed({}, 10))
        self.assertIsNone(assess_typing_speed({'typing_speed_samples': [5]}, None))
        self.assertIsNone(assess_typing_speed({'typing_speed_samples': [5]}, 0))


if __name__ == '__main__':
    unittest.main()
