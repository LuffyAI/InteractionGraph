"""Helpers for registering and installing the local Codex plugin."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class Installer:
    """Install through Codex's plugin commands without editing its configuration."""

    def __init__(self, executable=None):
        self.project = Path(__file__).resolve().parent.parent
        self.executable = executable

    def register(self):
        """Register the plugin while preserving other local marketplace entries."""
        target = self.project / ".agents/plugins/marketplace.json"
        if target.exists():
            catalog = json.loads(target.read_text())
        else:
            catalog = {"name": "codex-local", "interface": {"displayName": "Codex Local"}, "plugins": []}
        entry = {
            "name": "codex",
            "source": {"source": "local", "path": "./codex"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
        entries = catalog.setdefault("plugins", [])
        entries[:] = [item for item in entries if item.get("name") != "codex"]
        entries.append(entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(catalog, indent=2) + "\n")
        print(f"Registered codex in {target}")
        print('Restart Codex, open Plugins, select this local marketplace, and install codex.')
        return catalog['name']

    def install_dotvectordb(self):
        """Clone DotVectorDB, install dependencies, and build and install its wheel."""
        repository = self.project / 'DotVectorDB'
        subprocess.run(['git', 'clone', 'https://github.com/LuffyAI/DotVectorDB.git',
                        str(repository)], check=True)
        for requirements in ('requirements.txt', 'requirements-dev.txt'):
            print(f'==> Installing {requirements}...', flush=True)
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', requirements],
                           check=True, cwd=repository)
        print('==> Uninstalling dotvectordb...', flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', 'dotvectordb'],
                       check=True, cwd=repository)
        print('==> Cleaning old builds...', flush=True)
        for path in [repository / 'build', repository / 'dist', *repository.glob('*.egg-info')]:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        print('==> Building package...', flush=True)
        subprocess.run([sys.executable, '-m', 'build'], check=True, cwd=repository)
        wheels = sorted((repository / 'dist').glob('*.whl'))
        if not wheels:
            raise FileNotFoundError('Build produced no wheel in DotVectorDB/dist')
        print('==> Installing newly built wheel...', flush=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', *map(str, wheels)],
                       check=True, cwd=repository)
        print('==> Done.', flush=True)

    def find_codex(self):
        """Locate a supplied executable, the CLI, or the bundled Linux runtime."""
        candidates = [self.executable] if self.executable else [
            shutil.which('codex'), '/usr/lib/chatgpt/resources/codex',
        ]
        for candidate in candidates:
            if candidate:
                resolved = shutil.which(str(candidate))
                if resolved and os.access(resolved, os.X_OK):
                    return resolved
        raise FileNotFoundError('Codex executable not found. Pass --codex /path/to/codex.')

    def install(self):
        """Create the catalog, register its source, and install the named plugin."""
        executable = self.find_codex()
        marketplace = self.register()
        subprocess.run([executable, 'plugin', 'marketplace', 'add', str(self.project)],
                       check=True, cwd=self.project)
        subprocess.run([executable, 'plugin', 'add', f'codex@{marketplace}'],
                       check=True, cwd=self.project)
        print('Plugin installed. Restart Codex and start a new chat.')
        print('Review and trust the hook commands when Codex prompts you.')

