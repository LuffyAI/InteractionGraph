#!/usr/bin/env python3
"""Register this plugin in its parent project's local marketplace."""
import argparse
import subprocess
from install_helpers import Installer


def main():
    """Register the plugin and optionally install it through Codex."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install_plugin', action='store_true',
                        help='Register and install the plugin through Codex')
    parser.add_argument('--install_nsf_mcp', action='store_true',
                        help='Add the NSF OKN MCP server through Codex')
    parser.add_argument('--codex', help='Path to the Codex executable')
    args = parser.parse_args()
    installer = Installer(args.codex)
    try:
        if args.install_nsf_mcp:
            subprocess.run([
                installer.find_codex(), 'mcp', 'add', 'nsf-okn', '--url',
                'https://apps.okn.us/okn-mcp-dev/mcp',
            ], check=True)
        elif args.install_plugin:
            installer.install()
        else:
            installer.register()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Plugin setup failed: {error}\n')


if __name__ == "__main__":
    main()
