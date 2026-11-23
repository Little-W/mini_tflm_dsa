#!/usr/bin/env python3
"""检查 IA 编译开关、物理 SRAM 和软件调度能力值的一致性。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import elaboration
from scripts.rtl.source_files import input_files
sys.path.insert(0, str(ROOT / "test/capacity"))
from run_raw_only_capability import module, parameter, run_logged
sys.path.insert(0, str(ROOT / "test/ps_compression"))
from planner_profile import normalize_profile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    sources = [source_root / path.relative_to(ROOT) if path.is_relative_to(ROOT / "rtl") else path
               for path in elaboration.source_files()]
    inputs = input_files(sources, source_root, [source_root / "include", ROOT / "asic/rtl"])
    hashes = {str(path): digest(path) for path in inputs}
    rows = []
    for bank_bytes, bank_count in ((2048, 7), (8192, 7), (8192, 8)):
        for compact in (0, 1):
            directory = args.out / f"bank{bank_bytes}_count{bank_count}_compact{compact}"
            directory.mkdir(parents=True, exist_ok=True)
            tree_path = directory / "elaborated.tree.json"
            command = ["verilator", "--json-only", "-DSYNTHESIS", "-DASIC_SYNTHESIS", "-Wno-fatal",
                "--top-module", "npu_axil_top", "--json-only-output", str(tree_path),
                "--Mdir", str(directory / "obj"), "-GDATA_WIDTH=16", "-GWEIGHT_WIDTH=16", "-GBUS_WIDTH=64",
                f"-GSHARED_BANK_BYTES={bank_bytes}", f"-GSHARED_BANK_COUNT={bank_count}",
                f"-GIA_COMPACT_ENABLE={compact}", "-GSIZE=16", "-GIA_CACHE_BLOCKS=4", "-GPS_FRAME_COUNT=16",
                "-GVECTOR_PE_COUNT=8", "-GIM2COL_CACHE_BYTES=4096", "-DGEMPACT_PS_COMPRESS=1",
                f"-DGEMMORA_PS_POOL_BYTES={(bank_count - 1) * bank_bytes}", "-DGEMMORA_PS_FORCE_RAW=1",
                "-I" + str(source_root / "include"), "-I" + str(ROOT / "asic/rtl"),
                "-I" + str(source_root / "rtl/npu/ps_compact"), *map(str, sources)]
            run_logged(command, directory / "elaboration.log")
            tree = json.loads(tree_path.read_text())
            top, core = module(tree, "npu_axil_top"), module(tree, "npu_top")
            registers = module(tree, "npu_axil_reg_if")
            profile = normalize_profile(dict(size=16, bus_width=64, ps_compress=True, ia_cache_blocks=4,
                ps_frame_count=16, ps_storage_rows=0, im2col_cache_bytes=4096,
                shared_bank_bytes=bank_bytes, shared_bank_count=bank_count,
                shared_total_bytes=bank_bytes * bank_count, force_raw=True,
                ia_compact_enable=compact), root=ROOT)
            expected = dict(PS_CAPS=profile["ps_caps"], SHARED_TOTAL_BYTES=profile["shared_total_bytes"],
                SHARED_BANK_BYTES=profile["shared_bank_bytes"], SHARED_IA_BANK_MASK=profile["shared_ia_bank_mask"],
                PS_POOL_BYTES=profile["ps_pool_bytes"],
                MATRIX_S8_BANKS=profile["matrix_output_banks"] & 0xffff,
                MATRIX_S16_BANKS=profile["matrix_output_banks"] >> 16)
            actual = {name: parameter(registers, name) for name in expected}
            if actual != expected or parameter(core, "IA_COMPACT_ENABLE") != compact:
                raise ValueError(f"Capability mismatch: {directory.name}, {actual}, {expected}")
            if not parameter(registers, "SHARED_CAPABLE"):
                raise ValueError("Shared capacity registers are inactive")
            if parameter(top, "MATRIX_SHARED_R_MAX") != (4 if bank_count >= 8 else 2) * bank_bytes // (512 if compact else 1024):
                raise ValueError("IA R maximum differs from physical capacity")
            cache = module(tree, "ia_loader_cache_mgr")
            if any(node.get("name") == "g_local_ram" for node in walk(cache)):
                raise ValueError("Local IA data RAM was elaborated")
            rows.append(dict(bank_bytes=bank_bytes, bank_count=bank_count, compact=compact,
                             registers=actual, r_max=parameter(top, "MATRIX_SHARED_R_MAX"),
                             reset_ia_bytes=bank_bytes, reset_ps_bytes=(bank_count - 1) * bank_bytes,
                             command=command, elaboration_sha256=digest(tree_path), passed=True))
            del tree
            tree_path.unlink()
            print(json.dumps({key: value for key, value in rows[-1].items() if key != "command"}), flush=True)
    if hashes != {str(path): digest(path) for path in inputs}:
        raise ValueError("Source input changed during elaboration")
    (args.out / "summary.json").write_text(json.dumps(dict(passed=True, source_sha256=hashes, profiles=rows), indent=2) + "\n")


def walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


if __name__ == "__main__":
    main()
