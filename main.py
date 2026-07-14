#!/usr/bin/env python3
"""C Media Player — entry point.

The application now lives in the ``cmediaplayer`` package; this thin launcher
just starts it. Kept as a top-level script so ``python main.py [files…]`` and
the installed launcher keep working exactly as before.

Importing ``cmediaplayer`` runs the package's window-embedding environment fix
(see cmediaplayer/__init__.py) before PyQt6/libmpv are loaded.
"""
from cmediaplayer.app import main

if __name__ == "__main__":
    main()
