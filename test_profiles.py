import copy
import json
import random
import tempfile
from pathlib import Path
import unittest

from app import PersonalAI, MIN_WINDOWS, FLOORS
from profiles import ProfileStore


def profile(name='Oak', base=100, dimensions=4):
    rng = random.Random(42)
    return {'name': name, 'schema_version': 2, 'salt': '00'*16, 'password': '00'*32,
            'keyboard': [[rng.gauss(base, 5), rng.gauss(base*1.6, 8), rng.gauss(40, 3)]
                         for _ in range(MIN_WINDOWS)],
            'mouse': [[rng.gauss(base*3, 12), rng.gauss(80, 4), rng.gauss(.4, .02)]
                      + ([rng.uniform(.05, .15)] if dimensions == 4 else [])
                      for _ in range(MIN_WINDOWS)]}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parent/'data'
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='test-', dir=temporary_root)
        self.assertTrue(Path(self.temporary.name).resolve().is_relative_to(temporary_root))
        self.addCleanup(self.temporary.cleanup)
        self.store = ProfileStore(self.temporary.name)

    def test_independent_storage_edit_and_delete(self):
        first, second = profile(), profile('Second user', 500)
        a, b = self.store.create(first), self.store.create(second)
        original_second = self.store.path(b).read_bytes()
        first['mouse'].append([350, 85, .5, .4])
        self.store.save(a, first)
        self.assertEqual(self.store.path(b).read_bytes(), original_second)
        self.assertEqual(len(self.store.load(a)['mouse']), MIN_WINDOWS+1)
        self.store.delete(a)
        self.assertEqual(self.store.entries(), [(b, 'Second user')])

    def test_typing_speed_and_mouse_mode_roundtrip_and_reject_invalid_values(self):
        data = profile()
        data['typing_speed_samples'] = [4.5, 5.0, 5.5]
        data['pause_mouse_while_typing'] = False
        identifier = self.store.create(data)
        loaded = self.store.load(identifier)
        self.assertEqual(loaded['typing_speed_samples'], [4.5, 5.0, 5.5])
        self.assertIs(loaded['pause_mouse_while_typing'], False)
        for bad in (float('nan'), float('inf'), -1, 0):
            data['typing_speed_samples'] = [bad]
            with self.assertRaises(ValueError):
                self.store.save(identifier, data)

    def test_original_profile_loads_without_rewriting_or_deleting_it(self):
        original = profile(dimensions=3)
        del original['name']
        path = Path(self.temporary.name)/'profile.json'
        content = json.dumps(original).encode()
        path.write_bytes(content)
        self.assertEqual(self.store.entries(), [('legacy', 'Original profile')])
        self.assertEqual(self.store.load('legacy'), original)
        self.store.create(profile('New user'))
        self.assertEqual(path.read_bytes(), content)

    def test_duplicate_name_and_path_traversal_are_rejected(self):
        self.store.create(profile())
        with self.assertRaises(ValueError):
            self.store.create(profile('OAK'))
        for name in ('../profile', '', 'Z'*32):
            with self.assertRaises(ValueError):
                self.store.path(name)

    def test_partial_edge_enrollment_roundtrips(self):
        original = profile(dimensions=3)
        original['mouse_enrollment'] = [[300, 80, .4, .12]]*12
        identifier = self.store.create(original)
        loaded = self.store.load(identifier)
        self.assertEqual(len(loaded['mouse_enrollment']), 12)
        self.assertEqual(len(loaded['mouse'][0]), 3)

    def test_last_selected_profile_is_saved_separately_from_behavior(self):
        first = self.store.create(profile())
        second = self.store.create(profile('Second user'))
        self.store.remember_selected(second)
        self.assertEqual(ProfileStore(self.temporary.name).selected_profile(), second)
        self.assertEqual(len(self.store.entries()), 2)
        self.assertNotEqual(first, second)

    def test_invalid_and_mixed_samples_are_rejected(self):
        for change in ('nan', 'mixed', 'credentials'):
            value = profile()
            if change == 'nan':
                value['mouse'][0][0] = float('nan')
            elif change == 'mixed':
                value['mouse'][0].pop()
            else:
                value['password'] = 'bad'
            with self.assertRaises(ValueError):
                self.store.create(value)

    def test_each_ai_uses_its_own_users_baseline(self):
        first, second = profile(base=100), profile('Second user', base=800)
        first_before, second_before = copy.deepcopy(first), copy.deepcopy(second)
        a, b = PersonalAI(first), PersonalAI(second)
        owner = [100, 160, 40]
        self.assertLess(a.assess('keyboard', owner, first['keyboard'])[0],
                        b.assess('keyboard', owner, second['keyboard'])[0])
        self.assertEqual(first, first_before)
        self.assertEqual(second, second_before)
        self.assertEqual(a.dimensions['mouse'], 4)

    def test_legacy_ai_accepts_new_live_vector_without_mixing_dimensions(self):
        value = profile(dimensions=3)
        ai = PersonalAI(value)
        risk, details = ai.assess('mouse', [300, 80, .4, .9], value['mouse'])
        self.assertTrue(0 <= risk <= 1)
        self.assertNotIn('edge_fraction', details)
        self.assertEqual(ai.dimensions['mouse'], 3)

    def test_screen_edges_are_scored_by_new_mouse_model(self):
        value = profile()
        ai = PersonalAI(value)
        normal, normal_details = ai.assess('mouse', [300, 80, .4, .1], value['mouse'])
        unusual, unusual_details = ai.assess('mouse', [300, 80, .4, 1], value['mouse'])
        self.assertIn('edge_fraction', normal_details)
        self.assertGreater(unusual_details['edge_fraction'], normal_details['edge_fraction'])
        self.assertGreater(unusual, normal)

    def test_every_saved_typing_and_mouse_criterion_can_raise_the_score(self):
        import statistics
        data = profile()
        ai = PersonalAI(data)
        for kind in ('keyboard', 'mouse'):
            usual = [statistics.median(column) for column in zip(*data[kind])]
            self.assertLess(ai.assess(kind, usual, data[kind])[0], .65)
            for index, floor in enumerate(FLOORS[kind]):
                changed = usual[:]
                changed[index] += floor*20
                with self.subTest(kind=kind, criterion=index):
                    self.assertGreater(ai.assess(kind, changed, data[kind])[0], .65)


if __name__ == '__main__':
    unittest.main()
