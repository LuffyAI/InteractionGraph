#!/usr/bin/env python3
"""Register this plugin in its parent project's local marketplace."""
import argparse
import subprocess
from install_helpers import Installer


def main():
    """Register the plugin and optionally build and install DotVectorDB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install_dotvectordb', action='store_true',
                        help='Clone DotVectorDB, install its requirements, and build and install it')
    parser.add_argument('--install_plugin', action='store_true',
                        help='Register and install the plugin through Codex')
    parser.add_argument('--codex', help='Path to the Codex executable')
    args = parser.parse_args()
    installer = Installer(args.codex)
    if args.install_dotvectordb:
        try:
            installer.install_dotvectordb()
        except (OSError, subprocess.CalledProcessError) as error:
            parser.exit(1, f'DotVectorDB installation failed: {error}\n')
    try:
        if args.install_plugin:
            installer.install()
        else:
            installer.register()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Plugin setup failed: {error}\n')


if __name__ == "__main__":
    main()
