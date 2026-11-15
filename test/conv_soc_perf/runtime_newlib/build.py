#!/usr/bin/env python3
"""Build the unmodified newlib RISC-V memory routines used by both SoC modes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from package_sources import NEWLIB_VERSION, SOURCE_SHA256

HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcc", required=True)
    parser.add_argument("--newlib-include", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--march", default="rv32im_zicsr_zicntr")
    args = parser.parse_args()
    gcc = str(Path(shutil.which(args.gcc) or args.gcc).resolve())
    if not gcc.endswith("gcc"):
        raise ValueError("--gcc must end in gcc")
    prefix = gcc[:-3]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for name, expected in SOURCE_SHA256.items():
        if digest(HERE / name) != expected:
            raise RuntimeError(f"unmodified upstream source check failed: {name}")
    source = HERE / "newlib/libc"
    flags = [f"-march={args.march}", "-mabi=ilp32", "-O3", "-ffreestanding",
             "-fno-builtin", "-fno-tree-loop-distribute-patterns",
             "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
             "-I", str(args.newlib_include.resolve()), "-I", str(source / "string")]
    commands = []
    log = []

    def run(command: list[str]) -> str:
        commands.append(command)
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        log.extend([shlex.join(command) + "\n", result.stdout])
        (out / "build.log").write_text("".join(log))
        if result.returncode:
            raise RuntimeError(f"runtime build failed; see {out / 'build.log'}")
        return result.stdout

    for filename in ("memcpy.c", "memset.S"):
        stem = Path(filename).stem
        run([gcc, *flags, "-MD", "-MF", str(out / (stem + ".d")), "-c",
             str(source / "machine/riscv" / filename), "-o", str(out / (stem + ".o"))])
    archive = out / "libnewlib_memory.a"
    run([prefix + "ar", "rcs", str(archive), str(out / "memcpy.o"), str(out / "memset.o")])
    symbols = run([prefix + "nm", str(archive)])
    if any(len(line.split()) >= 2 and line.split()[-2] == "U" for line in symbols.splitlines()):
        raise RuntimeError("memory subset must have no undefined symbols")
    attributes = run([prefix + "readelf", "-h", "-A", str(archive)])
    (out / "symbols.txt").write_text(symbols)
    (out / "elf_attributes.txt").write_text(attributes)
    dependencies = {}
    for filename in ("memcpy.d", "memset.d"):
        content = (out / filename).read_text().replace("\\\n", " ").split(":", 1)[1]
        for value in shlex.split(content):
            path = Path(value).resolve()
            dependencies[str(path)] = digest(path)
    multilib_flags = [f"-march={args.march}", "-mabi=ilp32"]
    libgcc = Path(run([gcc, *multilib_flags, "-print-libgcc-file-name"]).strip()).resolve()
    manifest = {
        "passed": True, "scope": "compile, ELF architecture, symbols and source integrity; execution is verified by the SoC benchmark",
        "newlib_version": NEWLIB_VERSION,
        "package_sources_sha256": digest(HERE / "package_sources.py"),
        "build_script_sha256": digest(Path(__file__).resolve()),
        "compiler": run([gcc, "--version"]).splitlines()[0],
        "compiler_sha256": digest(Path(gcc)),
        "multilib_directory": run([gcc, *multilib_flags, "-print-multi-directory"]).strip(),
        "libgcc": str(libgcc), "libgcc_sha256": digest(libgcc),
        "commands": commands,
        "source_sha256": dependencies,
        "library": str(archive), "library_sha256": digest(archive),
        "library_bytes": archive.stat().st_size,
        "warning_exception": "only unused parameters in unmodified newlib locale inline headers",
        "memory_routines_modified": False,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: manifest[key] for key in ("passed", "newlib_version", "multilib_directory", "library", "library_sha256")}))


if __name__ == "__main__":
    main()
