import unittest
from unittest.mock import Mock, patch
from app import vector, score, password_hash, PersonalAI, MIN_WINDOWS, lock_windows
import random


class BehaviorTests(unittest.TestCase):
    def test_native_lock_requests_locking_without_claiming_a_verified_lock(self):
        user = Mock()
        user.LockWorkStation.return_value = 1
        with patch('app.ctypes.WinDLL', return_value=user) as load:
            self.assertTrue(lock_windows())
        load.assert_called_once_with('user32', use_last_error=True)
        user.LockWorkStation.assert_called_once_with()

    def test_native_lock_preserves_windows_failure_code(self):
        user = Mock()
        user.LockWorkStation.return_value = 0
        with patch('app.ctypes.WinDLL', return_value=user), patch('app.ctypes.get_last_error', return_value=5):
            with self.assertRaises(OSError) as raised:
                lock_windows()
        self.assertEqual(raised.exception.winerror, 5)

    def test_ai_separates_synthetic_cluster_from_extreme_sample(self):
        rng = random.Random(42)
        profile = {k: [[rng.gauss(100, 5), rng.gauss(160, 8), rng.gauss(40, 3)]
                       for _ in range(80)] for k in ('keyboard', 'mouse')}
        ai = PersonalAI(profile)
        for k in profile:
            normal = ai.assess(k, [100, 160, 40], profile[k])[0]
            unusual = ai.assess(k, [1000, 1600, 400], profile[k])[0]
            self.assertLess(normal, .60)
            self.assertGreater(unusual, .65)

    def test_ai_requires_enough_active_samples_even_when_timer_finishes(self):
        with self.assertRaises(ValueError):
            PersonalAI({k: [[100, 160, 40]]*(MIN_WINDOWS-1) for k in ('keyboard', 'mouse')})

    def test_ai_rejects_nonfinite_features(self):
        with self.assertRaises(ValueError):
            PersonalAI({k: [[float('nan'), 160, 40]]*MIN_WINDOWS for k in ('keyboard', 'mouse')})

    def test_idle_is_not_a_sample(self):
        self.assertIsNone(vector('keyboard', ([], [])))
        self.assertIsNone(vector('mouse', ([], [])))

    def test_straight_mouse_movement_is_valid_activity(self):
        self.assertEqual(vector('mouse', ([100]*20, [])), [100, 0, 0])

    def test_baseline_and_different_behavior(self):
        baseline = [[100, 160, 40]]*12
        self.assertEqual(score('keyboard', [100, 160, 40], baseline)[0], 0)
        self.assertGreater(score('keyboard', [350, 700, 250], baseline)[0], 3.5)

    def test_outlier_does_not_shift_median(self):
        baseline = [[100, 160, 40]]*12+[[9000, 9000, 9000]]
        self.assertEqual(score('keyboard', [100, 160, 40], baseline)[0], 0)

    def test_password_salted(self):
        self.assertNotEqual(password_hash('example passphrase', '00'*16),
                            password_hash('example passphrase', '01'*16))


if __name__ == '__main__':
    unittest.main()
