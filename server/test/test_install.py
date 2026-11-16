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

    def test_dotvectordb_build_cleans_artifacts_and_uses_current_python(self):
        with tempfile.TemporaryDirectory() as directory:
            installer = Installer()
            installer.project = Path(directory)
            repository = installer.project / 'DotVectorDB'
            for name in ('build', 'dist', 'old.egg-info'):
                (repository / name).mkdir(parents=True)
                (repository / name / 'stale').write_text('old')
            (repository / 'source.py').write_text('keep')
            wheel = repository / 'dist' / 'dotvectordb-test.whl'

            def run(command, **kwargs):
                if command == [sys.executable, '-m', 'build']:
                    for name in ('build', 'dist', 'old.egg-info'):
                        self.assertFalse((repository / name).exists())
                    wheel.parent.mkdir()
                    wheel.touch()

            with patch('install_helpers.subprocess.run', side_effect=run) as execute, \
                    patch('builtins.print'):
                installer.install_dotvectordb()
            commands = [call.args[0] for call in execute.call_args_list]
            self.assertEqual(commands[1:], [
                [sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'],
                [sys.executable, '-m', 'pip', 'install', '-r', 'requirements-dev.txt'],
                [sys.executable, '-m', 'pip', 'uninstall', '-y', 'dotvectordb'],
                [sys.executable, '-m', 'build'],
                [sys.executable, '-m', 'pip', 'install', str(wheel)],
            ])
            for call in execute.call_args_list[1:]:
                self.assertEqual(call.kwargs['cwd'], repository)
                self.assertTrue(call.kwargs['check'])
            self.assertEqual((repository / 'source.py').read_text(), 'keep')

    def test_requirements_failure_stops_before_uninstall_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            installer = Installer()
            installer.project = Path(directory)
            build = installer.project / 'DotVectorDB' / 'build'
            build.mkdir(parents=True)
            with patch('install_helpers.subprocess.run', side_effect=[
                None, subprocess.CalledProcessError(1, 'pip'),
            ]) as execute, patch('builtins.print'):
                with self.assertRaises(subprocess.CalledProcessError):
                    installer.install_dotvectordb()
            self.assertEqual(execute.call_count, 2)
            self.assertTrue(build.exists())
