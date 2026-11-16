import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'codex'))
from install_helpers import Installer


class InstallerTests(unittest.TestCase):
    def test_registration_preserves_catalog_and_does_not_duplicate_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            target = project / '.agents/plugins/marketplace.json'
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'name': 'custom', 'plugins': [{'name': 'other'}]}))
            installer = Installer()
            installer.project = project
            self.assertEqual(installer.register(), 'custom')
            installer.register()
            catalog = json.loads(target.read_text())
            self.assertEqual([entry['name'] for entry in catalog['plugins']], ['other', 'codex'])

    def test_install_uses_catalog_name_and_stops_if_registration_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            installer = Installer()
            installer.project = Path(directory)
            with patch.object(installer, 'find_codex', return_value='/bin/codex'), \
                    patch('install_helpers.subprocess.run') as run, patch('builtins.print'):
                installer.install()
                self.assertEqual(run.call_args_list[0].args[0], [
                    '/bin/codex', 'plugin', 'marketplace', 'add', directory,
                ])
                self.assertEqual(run.call_args_list[1].args[0], [
                    '/bin/codex', 'plugin', 'add', 'codex@codex-local',
                ])
                run.reset_mock()
                run.side_effect = subprocess.CalledProcessError(1, 'codex')
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install()
                self.assertEqual(run.call_count, 1)

    def test_missing_executable_leaves_catalog_untouched(self):
        installer = Installer('/missing/codex')
        with patch('install_helpers.shutil.which', return_value=None), patch.object(installer, 'register') as save:
            with self.assertRaises(FileNotFoundError):
                installer.install()
            save.assert_not_called()
