#!/usr/bin/env python3
"""使用完整 PS 模块的 Verilator 展开结果核对容量寄存器及逻辑状态总量。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))
sys.path.insert(0, str(ROOT / "test/ia_timing"))
from scripts.capacity import elaboration, model
from scripts.rtl.source_files import with_dependencies
from rtl_reference import read_rtl_source_group
from run_interface import port_declarations

SOURCE = Path("rtl/npu/ps_compact/ps_frame_store.sv")
PROFILES = (
    dict(name="small_shared", cache=4, frames=16, pool=10240,
         bank_bytes=2048, bank_count=6, shared=True, compact=False),
    dict(name="report_shared", cache=4, frames=16, pool=49152,
         bank_bytes=8192, bank_count=7, shared=True, compact=False),
    dict(name="performance_shared", cache=4, frames=16, pool=32768,
         bank_bytes=4096, bank_count=9, shared=True, compact=False),
    dict(name="compact_shared", cache=4, frames=16, pool=65536,
         bank_bytes=8192, bank_count=9, shared=True, compact=True),
    dict(name="private", cache=2, frames=3, pool=4096,
         bank_bytes=2048, bank_count=None, shared=False, compact=False),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wrapper(source, parameters):
    header = source[:source.index("\n);" + "\n") + len("\n);")]
    header = header[header.index("module ps_frame_store #("):]
    header = header.replace("module ps_frame_store #(", "module npu_axil_top #(", 1)
    ports = port_declarations(source)
    return header + "\nps_frame_store #(\n" + ",\n".join(
        f"    .{name}({name})" for name in parameters
    ) + "\n) u_store (\n" + ",\n".join(
        f"    .{name}({name})" for _, _, name, _ in ports
    ) + "\n);\nendmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7142f8ee41342454d9e27cae078c8e35a584685c")
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    reference = out / "reference.sv"
    reference.write_text(read_rtl_source_group(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    results = []
    tracked = {ROOT / SOURCE, Path(__file__).resolve(),
               ROOT / "scripts/capacity/model.py", ROOT / "scripts/capacity/elaboration.py"}
    for profile in PROFILES:
        geometry = dict(shared=profile["shared"], bank_bytes=profile["bank_bytes"],
                        bank_count=profile["bank_count"], ia_compact_enable=profile["compact"])
        dimensions = (profile["cache"], profile["frames"], profile["pool"])
        layout = model.memory_geometry(*dimensions, **geometry)
        expected = {name: bits for name, bits in model.register_arrays_bits(
            *dimensions, **geometry).items() if name.startswith("ps_")}
        parameters = dict(MAX_FRAME_ROWS=layout["max_frame_rows"], FRAME_COUNT=profile["frames"],
                          POOL_BYTES=profile["pool"], BANK_BYTES=profile["bank_bytes"],
                          EXTERNAL_RAM=int(profile["shared"]), p_fixed_ps_channels=int(profile["shared"]))
        inventories = {}
        for label, rtl in (("current", ROOT / SOURCE), ("reference", reference)):
            folder = out / profile["name"] / label
            folder.mkdir(parents=True, exist_ok=True)
            top = folder / "top.sv"
            top.write_text(wrapper(source, parameters))
            tree_path = folder / "elaborated.tree.json"
            sources = with_dependencies([rtl, top], ROOT)
            tracked.update(path for path in sources if path.is_relative_to(ROOT))
            command = [args.verilator, "--json-only", "-DSYNTHESIS", "-Wno-fatal",
                       "--top-module", "npu_axil_top", "--json-only-output", str(tree_path),
                       "--Mdir", str(folder / "obj"),
                       *(f"-G{name}={value}" for name, value in parameters.items()), *map(str, sources)]
            with (folder / "elaboration.log").open("w") as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
            tree_digest = digest(tree_path)
            state = elaboration.inventory(json.loads(tree_path.read_text()))
            tree_path.unlink()
            inventories[label] = dict(total_bits=state["total_bits"],
                buffer_arrays_bits=state["buffer_arrays_bits"],
                register_arrays_bits=state["register_arrays_bits"],
                sequential_declarations=state["sequential_declarations"], tree_sha256=tree_digest)
        current, previous = inventories["current"], inventories["reference"]
        assert current["register_arrays_bits"] == expected, (profile, current, expected)
        assert current["buffer_arrays_bits"] == previous["buffer_arrays_bits"]
        difference = current["total_bits"] - previous["total_bits"]
        assert difference == expected["ps_capacity_limits"] - 25, (profile, difference)
        if profile["name"] == "report_shared":
            assert expected == dict(ps_capacity_limits=224, ps_request_context=55, ps_completion_flags=6)
            assert difference == 199
        result = dict(passed=True, profile=profile, parameters=parameters,
                      expected_register_arrays_bits=expected, logical_state_delta_bits=difference,
                      versions=inventories)
        results.append(result)
        print(json.dumps(dict(profile=profile["name"], passed=True,
                              logical_state_delta_bits=difference)), flush=True)
    assert (ROOT / SOURCE).read_text() == source
    summary = dict(passed=True, reference=args.reference, profiles=results,
                   source_sha256={str(path.relative_to(ROOT)): digest(path) for path in sorted(tracked)})
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
