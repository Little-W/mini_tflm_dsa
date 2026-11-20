#!/usr/bin/env python3
"""使用真实 DC 源文件准备流程检查生产 NPU 的 ASIC 存储层次。"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PARAMETERS = {
    "WEIGHT_WIDTH": 16, "DATA_WIDTH": 16, "SIZE": 16, "BUS_WIDTH": 64,
    "REG_WIDTH": 32, "ADDR_WIDTH": 19,
    "SHARED_BANK_BYTES": 8192, "SHARED_BANK_COUNT": 7, "IA_CACHE_BLOCKS": 4,
    "PS_FRAME_COUNT": 16, "IM2COL_CACHE_BYTES": 4096,
    "AXI_READ_OUTSTANDING": 4, "AXI_WRITE_OUTSTANDING": 4,
    "ENABLE_VECTOR_ENGINE": 1, "VECTOR_PE_COUNT": 8,
    "ENABLE_IS_MODE": 1, "ENABLE_PER_CHANNEL": 1,
}
DEFINES = [
    "SYNTHESIS=1", "ASIC_SYNTHESIS=1", "ASIC_SRAM=1",
    "GEMPACT_PS_COMPRESS=1", "GEMMORA_PS_POOL_BYTES=49152", "GEMMORA_PS_FORCE_RAW=1",
]
MACROS = ("RAMTP128X16", "RAMTP1024X16")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, cwd, timeout=600):
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout)
    if result.returncode:
        raise RuntimeError("Command failed: " + str(log) + "\n" + log.read_text()[-6000:])


def input_files(root):
    """保存 DC 文件列表、源文件、头文件及实际调用的准备程序。"""
    filelist = root / "asic/synthesis/filelists/npu_top.f"
    paths = {filelist, root / "scripts/asic/prepare_dc_sources.py",
             root / "asic/rtl/smic40_sram_1r1w.sv",
             root / "asic/synthesis/scripts/3_read_design.tcl"}
    for line in filelist.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("+incdir+"):
            folder = (filelist.parent.parent / line[8:]).resolve()
            paths.update(p for p in folder.rglob("*") if p.suffix in (".svh", ".vh"))
        else:
            paths.add((filelist.parent.parent / line).resolve())
    return sorted(paths)


def number(value):
    if isinstance(value, int):
        return value
    return int(value, 2) if re.fullmatch(r"[01]+", value) else value


def original_name(name, module):
    origin = module.get("attributes", {}).get("hdlname", "").split()
    if origin:
        return origin[0]
    return name.split("$", 1)[0]


def inspect(design):
    """按真实实例递归计数，并单独收集量化缓冲的整个子层次。"""
    modules = design["modules"]
    instances = Counter()
    rows = []
    memories = []
    group_roots = []

    def visit(name, path, ancestors):
        module = modules[name]
        origin = original_name(name, module)
        lineage = ancestors + (origin,)
        instances[origin] += 1
        row = {"path": path, "module": origin, "specialization": name,
               "port_widths": {k: len(v["bits"]) for k, v in module.get("ports", {}).items()},
               "blackbox": bool(number(module.get("attributes", {}).get("blackbox", 0)))}
        rows.append(row)
        if origin == "requant_group_buffer":
            if "vec_requant" not in ancestors:
                raise RuntimeError("Group buffer is outside the real vec_requant hierarchy")
            group_roots.append(row)
        for cell_name, cell in module.get("cells", {}).items():
            cell_type = cell["type"]
            child_path = path + "/" + cell_name
            if cell_type in modules:
                visit(cell_type, child_path, lineage)
            elif cell_type.startswith("$mem"):
                memories.append({"path": child_path, "type": cell_type,
                                 "inside_group_buffer": "requant_group_buffer" in lineage})
            elif not cell_type.startswith("$"):
                raise RuntimeError("Unresolved module: " + cell_type)

    visit("npu_top", "npu_top", ())
    if len(group_roots) != 1:
        raise RuntimeError("Expected one complete NPU requant_group_buffer")
    group = group_roots[0]
    subtree = [row for row in rows if row["path"].startswith(group["path"] + "/")]
    macro_rows = [row for row in subtree if row["module"] in MACROS]
    group_memories = [row for row in memories if row["inside_group_buffer"]]
    if group_memories or any(row["module"] == "regfile" for row in subtree):
        raise RuntimeError("Group buffer contains inferred storage arrays")
    if Counter(row["module"] for row in macro_rows) != {"RAMTP128X16": 132}:
        raise RuntimeError("Unexpected group-buffer SRAM macro geometry")
    group_module = modules[group["specialization"]]
    group_state = {name: len(group_module["netnames"][name]["bits"])
                   for name in ("read_addr_q", "write_addr_q", "stored_rows_q", "pending_rows_q")}
    # 九位地址和十位占用计数同时成立时，现有计数器定义对应恰好 512 行。
    if group_state != {"read_addr_q": 9, "write_addr_q": 9,
                       "stored_rows_q": 10, "pending_rows_q": 10} or \
            any(group["port_widths"][name] != 512 for name in ("i_row_data", "o_row_data")):
        raise RuntimeError("Unexpected group-buffer logical capacity")
    wrappers = [row for row in subtree if row["module"] == "smic40_sram_1r1w"]
    if len(wrappers) != 1:
        raise RuntimeError("Expected one group-buffer SRAM wrapper")
    wrapper_widths = wrappers[0]["port_widths"]
    expected_widths = {"write_data": 513, "read_data": 513, "write_mask": 513,
                       "write_address": 9, "read_address": 9}
    if any(wrapper_widths.get(k) != v for k, v in expected_widths.items()):
        raise RuntimeError("SRAM wrapper geometry differs from the logical row capacity")
    bank_lanes = Counter()
    for row in macro_rows:
        match = re.search(r"g_bank\[(\d+)\].*g_lane\[(\d+)\]", row["path"])
        if not match or not row["blackbox"]:
            raise RuntimeError("SRAM macro hierarchy or blackbox declaration differs")
        bank_lanes[int(match[1])] += 1
        if int(match[2]) not in range(33):
            raise RuntimeError("SRAM width index is outside the expected range")
    if bank_lanes != {0: 33, 1: 33, 2: 33, 3: 33}:
        raise RuntimeError("SRAM depth banks are incomplete")
    sequential_bits = 0
    for row in [group] + subtree:
        if row["blackbox"]:
            continue
        for cell in modules[row["specialization"]].get("cells", {}).values():
            if "latch" in cell["type"]:
                raise RuntimeError("Group buffer contains a latch")
            if "dff" in cell["type"]:
                sequential_bits += number(cell["parameters"]["WIDTH"])
    if sequential_bits != 41:
        raise RuntimeError("Group-buffer state differs from its 39 control bits and 2 bank-select bits")
    expected_instances = {"npu_top": 1, "compute_core": 1, "ws_systolic_array": 1,
                          "ws_systolic_cell": 256, "vector_engine": 1, "vector_pe": 8,
                          "requant_group_buffer": 1, "ia_ps_shared_ram": 1}
    if any(instances[k] != v for k, v in expected_instances.items()):
        raise RuntimeError("Complete NPU compute or shared-memory dimensions differ: " +
                           json.dumps(dict(instances), sort_keys=True))
    for row in rows:
        if row["blackbox"] and row["module"] not in MACROS:
            raise RuntimeError("Unexpected blackboxed NPU logic: " + row["path"])
    top_widths = rows[0]["port_widths"]
    if any(top_widths.get(k) != v for k, v in
           {"m_axi_rdata": 64, "m_axi_wdata": 64, "m_axi_wstrb": 8}.items()):
        raise RuntimeError("Production NPU bus dimensions differ after elaboration")
    for macro, address_width in (("RAMTP128X16", 7), ("RAMTP1024X16", 10)):
        ports = modules[macro]["ports"]
        expected_ports = {"QA": ("output", 16), "CLKA": ("input", 1), "CENA": ("input", 1),
                          "AA": ("input", address_width), "CLKB": ("input", 1), "CENB": ("input", 1),
                          "WENB": ("input", 16), "AB": ("input", address_width), "DB": ("input", 16),
                          "EMAA": ("input", 3), "EMAB": ("input", 3),
                          "RET1N": ("input", 1), "COLLDISN": ("input", 1)}
        if {k: (v["direction"], len(v["bits"])) for k, v in ports.items()} != expected_ports:
            raise RuntimeError("SRAM blackbox port dimensions differ")
    return {
        "module_instances": dict(sorted(instances.items())),
        "expected_compute_instances": expected_instances,
        "top_port_widths": top_widths,
        "group_buffer": {
            "path": group["path"], "lanes": 16, "rows": 512,
            "state_widths": group_state, "wrapper_port_widths": wrapper_widths,
            "macro_instances": len(macro_rows), "macro_type": "RAMTP128X16",
            "macros_per_depth_bank": dict(sorted(bank_lanes.items())),
            "logical_storage_bits": 513 * 512,
            "physical_macro_storage_bits": 132 * 128 * 16,
            "physical_macro_storage_bytes": 132 * 128 * 16 // 8,
            "inferred_memory_cells": 0, "regfile_instances": 0,
            "control_and_bank_select_register_bits": sequential_bits,
            "macro_paths": [row["path"] for row in macro_rows],
        },
        "all_sram_macros": {name: instances[name] for name in MACROS},
        "other_inferred_memory_cells": len(memories),
        "all_non_macro_hierarchy_elaborated": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--keep-netlist", action="store_true")
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys as yosys
        yosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    if args.out is None:
        parser.error("--out is required")
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    snapshot = out / "snapshot"
    sources = input_files(root)
    hashes = {str(path.relative_to(root)): digest(path) for path in sources}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    for path in sources:
        target = snapshot / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if hashes != {str(path.relative_to(snapshot)): digest(path)
                  for path in (snapshot / relative for relative in hashes)}:
        raise RuntimeError("Source snapshot differs from the recorded input files")
    prepared = out / "dc_sources"
    prepare_command = [sys.executable, str(snapshot / "scripts/asic/prepare_dc_sources.py"),
                       "--root", str(snapshot), "--out", str(prepared)]
    run(prepare_command, out / "prepare.log", snapshot)
    prepared_filelist = prepared / "sources.f"
    compilation_files, includes = [], []
    for line in prepared_filelist.read_text().splitlines():
        if line.startswith("+incdir+"):
            includes.append(line[8:])
        elif line.strip():
            compilation_files.append(Path(line))
    # DC 在文件列表末尾追加同一 SRAM 封装，结构检查沿用该顺序。
    compilation_files.append(snapshot / "asic/rtl/smic40_sram_1r1w.sv")
    blackboxes = out / "sram_blackboxes.sv"
    shutil.copy2(HERE / "sram_blackboxes.sv", blackboxes)
    compilation_files.append(blackboxes)
    (out / "elaboration.f").write_text("\n".join(
        ["+incdir+" + path for path in includes] + list(map(str, compilation_files))) + "\n")
    options = ["read_slang", "--keep-hierarchy", "--top", "npu_top"]
    options += ["-D" + item for item in DEFINES]
    options += ["-G" + name + "=" + str(value) for name, value in PARAMETERS.items()]
    options += ["-I" + path for path in includes]
    options += [str(path) for path in compilation_files]
    netlist, script, log = out / "npu.json", out / "elaborate.ys", out / "elaboration.log"
    script.write_text(" ".join(map(shlex.quote, options)) + "\n" +
                      "hierarchy -check -top npu_top\nproc\nopt_clean\nmemory_collect\ncheck -assert\n" +
                      "write_json " + shlex.quote(str(netlist)) + "\n")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(script)]
    run(command, log, snapshot)
    design = json.loads(netlist.read_text())
    result = inspect(design)
    unchanged = hashes == {str(path.relative_to(root)): digest(path) for path in sources}
    if not unchanged:
        raise RuntimeError("Source inputs changed during complete NPU elaboration")
    result.update({
        "passed": True, "source_root": str(root), "source_commit": commit,
        "source_sha256": hashes, "sources_unchanged": unchanged,
        "snapshot_sha256": {relative: digest(snapshot / relative) for relative in hashes},
        "prepared_source_sha256": {str(path.relative_to(prepared)): digest(path)
                                    for path in compilation_files if path.is_relative_to(prepared)},
        "prepare_script_sha256": hashes["scripts/asic/prepare_dc_sources.py"],
        "prepared_filelist_sha256": digest(prepared_filelist),
        "blackbox_source_sha256": digest(blackboxes),
        "checker_source_sha256": digest(Path(__file__).resolve()),
        "elaboration_script_sha256": digest(script), "elaborated_netlist_sha256": digest(netlist),
        "tool": design.get("creator", "Yosys with Slang"),
        "structural_frontend": "Yosys read_slang --keep-hierarchy",
        "defines": DEFINES, "parameters": PARAMETERS,
        "prepare_command": prepare_command, "elaboration_command": command,
        "dc_synthesis_performed": False, "technology_library_used": False,
        "macro_behavior_simulated": False,
        "validation_scope": "真实 DC 源文件准备及完整 NPU 层次展开、端口连接、存储几何与计算单元数量",
        "elapsed_seconds": round(time.monotonic() - started, 3),
    })
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if not args.keep_netlist:
        with netlist.open("rb") as source, gzip.open(str(netlist) + ".gz", "wb") as destination:
            shutil.copyfileobj(source, destination)
        netlist.unlink()
    print(json.dumps({"passed": True, "tool": result["tool"],
                      "group_buffer_macro_instances": result["group_buffer"]["macro_instances"],
                      "group_buffer_inferred_memory_cells": 0,
                      "systolic_cells": result["module_instances"]["ws_systolic_cell"],
                      "vector_pe": result["module_instances"]["vector_pe"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
