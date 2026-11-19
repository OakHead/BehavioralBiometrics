import unittest

from detection import (ThreatTimer, PositionModel, DwellWatch, clock_text, duration_seconds,
                       dwell_limits, learned_mouse_limit)
from metrics import MouseHeatmap, ScreenLayout


class DetectionTests(unittest.TestCase):
    def test_1000ms_hold_is_immediate_against_300ms_learning(self):
        limits = dwell_limits({'key_hold_samples': [300]*20})
        watch = DwellWatch()
        reason = watch.observe(0, [(1, 1000)], [], limits)
        self.assertEqual(reason['observed'], 1000)
        self.assertEqual(reason['typical'], 300)
        self.assertIn('1000 ms', reason['text'])

    def test_live_hold_is_checked_before_release(self):
        watch = DwellWatch()
        limits = dwell_limits({'key_hold_samples': [300]*20})
        self.assertIsNone(watch.observe(0, [], [(1, 600)], limits))
        self.assertEqual(watch.observe(.5, [], [(1, 601)], limits)['kind'], 'key_dwell')

    def test_normal_typing_cancels_a_pending_long_hold(self):
        watch = DwellWatch()
        limits = dwell_limits({'key_hold_samples': [300]*20})
        watch.observe(0, [(1, 1000)], [], limits)
        watch.observe(.5, [(2, 300)], [], limits)
        for step in range(2, 20):
            self.assertIsNone(watch.observe(step*.5, [], [], limits))
        self.assertIsNone(watch.pending)

    def test_approved_hold_remains_accepted_even_with_a_large_old_sample_history(self):
        maximum, limit = dwell_limits({'key_hold_samples': [300]*500, 'key_dwell_max_ms': 1000})
        self.assertEqual(maximum, 1000)
        self.assertEqual(limit, 2000)

    def test_old_mouse_profile_gets_a_conservative_cap_until_new_learning(self):
        self.assertEqual(learned_mouse_limit({'mouse': [[100, 20, .4, 0]]}), 160)
        self.assertEqual(learned_mouse_limit({'mouse': [[100, 20, .4, 0]], 'mouse_speed_limit': 900}), 900)

    def test_alert_requires_more_than_five_real_seconds(self):
        timer = ThreatTimer()
        for step in range(10):
            self.assertFalse(timer.update(step*.5, True))
        self.assertTrue(timer.update(5, True))

    def test_normal_activity_breaks_the_continuous_period(self):
        timer = ThreatTimer()
        for step in range(10):
            timer.update(step*.5, True)
        self.assertFalse(timer.update(5, False))
        self.assertFalse(timer.update(5.5, True))
        self.assertEqual(timer.since, 5.5)

    def test_idle_and_stalled_checks_do_not_count_as_continuous(self):
        timer = ThreatTimer()
        timer.update(0, True)
        self.assertFalse(timer.update(10, True))
        self.assertEqual(timer.since, 10)
        self.assertFalse(timer.update(10.5, True, active=False))
        self.assertIsNone(timer.since)

    def test_grace_is_exactly_sixty_seconds_then_a_fresh_five_seconds_is_required(self):
        timer = ThreatTimer()
        timer.grant_grace(10)
        for now in (10, 30, 65, 69.999):
            self.assertFalse(timer.update(now, True))
        self.assertEqual(timer.grace_left(70), 0)
        for step in range(10):
            self.assertFalse(timer.update(70+step*.5, True))
        self.assertTrue(timer.update(75, True))

    def test_chosen_training_time_and_countdown(self):
        self.assertEqual(duration_seconds('2', 'minutes'), 120)
        self.assertEqual(duration_seconds('30', 'seconds'), 30)
        self.assertEqual(clock_text(65.1), '01:06')
        for value in ('nan', 'inf', '-1', '0', 'abc', '3601'):
            with self.assertRaises(ValueError):
                duration_seconds(value, 'seconds')

    def test_cursor_area_is_compared_with_saved_behavior(self):
        layout = ScreenLayout(((0, 0, 1000, 1000),))
        saved = MouseHeatmap(layout)
        saved.add(100, 100, 30)
        model = PositionModel(saved)
        usual, different = MouseHeatmap(layout), MouseHeatmap(layout)
        usual.add(100, 100, 1)
        different.add(900, 900, 1)
        self.assertLess(model.assess(usual), .60)
        self.assertGreater(model.assess(different), .70)

    def test_unknown_monitor_layout_does_not_invent_cursor_area_knowledge(self):
        saved = MouseHeatmap(ScreenLayout(((0, 0, 1000, 1000),)))
        saved.add(100, 100, 10)
        other = MouseHeatmap(ScreenLayout(((-1000, 0, 0, 1000),)))
        other.add(-500, 500, 1)
        self.assertIsNone(PositionModel(saved).assess(other))


if __name__ == '__main__':
    unittest.main()
