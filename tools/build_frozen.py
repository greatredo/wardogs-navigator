"""Run PyInstaller with native dependency lookup isolated from external tools.

Set PATH inside the build interpreter: process launchers can restore their own
PATH when starting Python, overriding a shell-level assignment. In particular,
Poppler's icuuc.dll cannot replace the Windows ICU library expected by Qt.
"""
import os
from pathlib import Path
import sys


def main():
    if sys.platform != "win32":
        raise SystemExit("Windows packaging must run on Windows")
    windows = Path(os.environ["SystemRoot"])
    os.environ["PATH"] = os.pathsep.join(
        str(path) for path in (
            Path(sys.executable).parent, Path(sys.base_prefix),
            windows / "System32", windows,
        )
    )
    from PyInstaller.__main__ import run
    run(sys.argv[1:])


if __name__ == "__main__":
    main()
