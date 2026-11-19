"""Startup behavior without recording input or opening a real protection session."""
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
import uuid

from launch import InstanceLock, Starter


class StartupTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(__file__).resolve().parent/'data'
        temporary_root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='startup-test-', dir=temporary_root)
        self.assertTrue(Path(self.temporary.name).resolve().is_relative_to(temporary_root))
        self.addCleanup(self.temporary.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.close)

    def close(self):
        self.root.update_idletasks()
        self.root.destroy()

    def finish_startup(self, starter):
        deadline = time.monotonic()+4
        while not starter.ready and not starter.failed and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(starter.ready or starter.failed, 'Startup did not report success or failure')

    def test_import_runs_in_background_and_app_opens_on_main_thread(self):
        threads = {}
        main_thread = threading.get_ident()

        def app(root):
            threads['app'] = threading.get_ident()

        def load():
            threads['import'] = threading.get_ident()
            return SimpleNamespace(App=app)

        starter = Starter(self.root, self.temporary.name, load)
        self.finish_startup(starter)
        self.assertTrue(starter.ready)
        self.assertEqual(threads['app'], main_thread)
        self.assertNotEqual(threads['import'], main_thread)

    def test_import_error_is_visible_and_saved_in_a_log(self):
        def load():
            raise RuntimeError('Simulated import failure')

        starter = Starter(self.root, self.temporary.name, load)
        self.finish_startup(starter)
        self.assertTrue(starter.failed)
        self.assertIn('Could not start', starter.status.get())
        self.assertIn('Simulated import failure', starter.status.get())
        self.assertIn('Simulated import failure', (Path(self.temporary.name)/'startup-error.log').read_text())

    def test_app_initialization_error_is_visible(self):
        def broken_app(root):
            raise RuntimeError('Simulated app initialization failure')

        starter = Starter(self.root, self.temporary.name, lambda: SimpleNamespace(App=broken_app))
        self.finish_startup(starter)
        self.assertTrue(starter.failed)
        self.assertIn('Simulated app initialization failure', starter.status.get())

    @unittest.skipUnless(os.name == 'nt', 'Windows instance lock')
    def test_only_one_launcher_instance_can_own_the_same_name(self):
        name = 'Local\\BehaviorGuard-startup-test-'+uuid.uuid4().hex
        first = InstanceLock(name)
        self.addCleanup(first.close)
        second = InstanceLock(name)
        self.addCleanup(second.close)
        self.assertTrue(first.first)
        self.assertFalse(second.first)
