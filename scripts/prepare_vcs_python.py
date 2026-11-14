#!/usr/bin/env python3
"""Make the host NumPy installation available to the VCS container."""

from pathlib import Path
import shutil
import sys

import numpy


def main():
    root = Path(__file__).resolve().parents[1]
    source = Path(numpy.__file__).resolve().parent.parent
    target = root / "build/vcs/python_deps"
    marker = target / ".numpy-version"
    version = f"{numpy.__version__} {sys.version_info.major}.{sys.version_info.minor}\n"
    if marker.is_file() and marker.read_text() == version:
        return
    target.mkdir(parents=True, exist_ok=True)
    for name in ("numpy", "numpy.libs"):
        origin = source / name
        if origin.is_dir():
            shutil.copytree(origin, target / name, dirs_exist_ok=True)
    marker.write_text(version)


if __name__ == "__main__":
    main()
