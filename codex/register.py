#!/usr/bin/env python3
"""Register this plugin in its parent project's local marketplace."""
import json
from pathlib import Path


def main():
    plugin = Path(__file__).resolve().parent
    project = plugin.parent
    target = project / ".agents/plugins/marketplace.json"
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
    print("Restart Codex, open Plugins, select this local marketplace, and install codex.")


if __name__ == "__main__":
    main()
