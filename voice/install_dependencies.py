#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Explicit online setup into an isolated target; never replaces GPU PyTorch."""

import argparse
import importlib.metadata as metadata
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    import torch
    import torchaudio
    if not torch.cuda.is_available():
        raise RuntimeError("Select a Python environment with working GPU PyTorch first; this installer does not install or replace Torch.")
    target = args.target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    requirements = Path(__file__).parent / "requirements-target.txt"
    uv = shutil.which("uv")
    prefix = [uv, "pip", "install", "--python", sys.executable] if uv else [sys.executable, "-m", "pip", "install"]
    command = [*prefix, "--target", str(target), "--no-deps", "-r", str(requirements)]
    subprocess.run(command, check=True, shell=False)
    # Reuse shared numerical/GPU packages; fill missing pure/runtime dependencies
    # into the same target rather than changing the selected base environment.
    shared = ["numpy", "scipy", "Pillow", "requests", "filelock", "fsspec", "packaging", "PyYAML", "regex", "tqdm", "psutil", "typing_extensions"]
    missing = []
    for package in shared:
        try:
            metadata.version(package)
        except metadata.PackageNotFoundError:
            missing.append(package)
    if missing:
        subprocess.run([*prefix, "--target", str(target), *missing], check=True, shell=False)
    print("Installed a process-local inference overlay. Start the service with --deps pointing to this target.")
    print("GPU PyTorch was reused and the base Python environment was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
