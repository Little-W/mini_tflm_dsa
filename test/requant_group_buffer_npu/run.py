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
    "ENABLE_VECTOR_ENGINE": 1, "VECTOR_PE_COUNT": 16,
    "ENABLE_IS_MODE": 1, "ENABLE_PER_CHANNEL": 1,
}
DEFINES = [
    "SYNTHESIS=1", "ASIC_SYNTHESIS=1", "ASIC_SRAM=1",
    "GEMPACT_PS_COMPRESS=1", "GEMMORA_PS_POOL_BYTES=49152", "GEMMORA_PS_FORCE_RAW=1",
]
MACROS = ("RAMTP128X16", "RAMTP1024X16")
PROFILES = {
    "820c": {"wrapper_small_depth_limit": 128, "bias_full_word_mask": False, "amount_pair_min_depth": None, "kernel_force_sram": False},
    "current": {"wrapper_small_depth_limit": 384, "bias_full_word_mask": True, "amount_pair_min_depth": 129, "kernel_force_sram": True},
}


def ceiling_log2(value):
    return max(1, (value - 1).bit_length())


def expected_capacity(parameters):
    """按 npu_top 与 matrix_engine 的生产参数推导完整分组容量。"""
    size, data_width = parameters["SIZE"], parameters["DATA_WIDTH"]
    physical_banks = parameters["SHARED_BANK_COUNT"]
    max_ia_banks = 4 if physical_banks >= 8 else 2
    bytes_per_tile = size * size * data_width // 8
    ia_cache_blocks = max_ia_banks * parameters["SHARED_BANK_BYTES"] // bytes_per_tile
    slots = ia_cache_blocks * (2 if parameters["IA_COMPACT_ENABLE"] and data_width == 16 else 1)
    ia_reuse = max(1, slots // 2)
    rows = size * ia_reuse
    return {"shared_physical_banks": physical_banks, "shared_max_ia_banks": max_ia_banks,
            "ia_max_cache_blocks": ia_cache_blocks, "ia_slot_blocks": slots,
            "ia_reuse_num_max": ia_reuse, "group_rows": rows,
            "group_address_width": ceiling_log2(rows), "group_count_width": ceiling_log2(rows + 1),
            "bias_logical_width": 64, "bias_logical_depth": rows,
            "product_amount_banks": 2, "product_amount_rows_per_bank": rows // 2}


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
    paths = {filelist, root / "asic/rtl/smic40_sram_1r1w.sv",
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


def inspect(design, parameters, implementation_profile):
    """按真实实例递归计数，并单独收集量化缓冲的整个子层次。"""
    capacity = expected_capacity(parameters)
    profile = PROFILES[implementation_profile]
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
                                 "inside_group_buffer": "requant_group_buffer" in lineage,
                                 "geometry": {key: number(value) for key, value in cell["parameters"].items()
                                              if key in ("WIDTH", "SIZE", "RD_PORTS", "WR_PORTS",
                                                         "RD_CLK_ENABLE", "WR_CLK_ENABLE")}})
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
    group_rows = capacity["group_rows"]
    group_address_width = capacity["group_address_width"]
    group_count_width = capacity["group_count_width"]
    macro_depth = 128 if group_rows <= profile["wrapper_small_depth_limit"] else 1024
    macro_type = f"RAMTP{macro_depth}X16"
    depth_banks = (group_rows + macro_depth - 1) // macro_depth
    width_lanes = (parameters["SIZE"] * 32 + 1 + 15) // 16
    if Counter(row["module"] for row in macro_rows) != {macro_type: depth_banks * width_lanes}:
        raise RuntimeError("Unexpected group-buffer SRAM macro geometry")
    group_module = modules[group["specialization"]]
    group_state = {name: len(group_module["netnames"][name]["bits"])
                   for name in ("read_addr_q", "write_addr_q", "stored_rows_q", "pending_rows_q")}
    expected_state = {"read_addr_q": group_address_width, "write_addr_q": group_address_width,
                      "stored_rows_q": group_count_width, "pending_rows_q": group_count_width}
    if group_state != expected_state or any(group["port_widths"][name] != parameters["SIZE"] * 32
                                           for name in ("i_row_data", "o_row_data")):
        raise RuntimeError("Unexpected group-buffer logical capacity")
    wrappers = [row for row in subtree if row["module"] == "smic40_sram_1r1w"]
    if len(wrappers) != 1:
        raise RuntimeError("Expected one group-buffer SRAM wrapper")
    wrapper_widths = wrappers[0]["port_widths"]
    expected_widths = {"write_data": 513, "read_data": 513, "write_mask": 513,
                       "write_address": group_address_width, "read_address": group_address_width}
    if any(wrapper_widths.get(k) != v for k, v in expected_widths.items()):
        raise RuntimeError("SRAM wrapper geometry differs from the logical row capacity")
    bank_lanes = Counter()
    found_coordinates = set()
    for row in macro_rows:
        match = re.search(r"g_bank\[(\d+)\].*g_lane\[(\d+)\]", row["path"])
        if not match or not row["blackbox"]:
            raise RuntimeError("SRAM macro hierarchy or blackbox declaration differs")
        coordinates = tuple(map(int, match.groups()))
        if coordinates in found_coordinates:
            raise RuntimeError("SRAM macro coordinate is duplicated")
        found_coordinates.add(coordinates)
        bank_lanes[coordinates[0]] += 1
    if found_coordinates != {(bank, lane) for bank in range(depth_banks) for lane in range(width_lanes)}:
        raise RuntimeError("SRAM depth banks or width slices are incomplete")
    sequential_bits = 0
    for row in [group] + subtree:
        if row["blackbox"]:
            continue
        for cell in modules[row["specialization"]].get("cells", {}).values():
            if "latch" in cell["type"]:
                raise RuntimeError("Group buffer contains a latch")
            if "dff" in cell["type"]:
                sequential_bits += number(cell["parameters"]["WIDTH"])
    expected_sequential_bits = 2 * group_address_width + 2 * group_count_width + 1 + ceiling_log2(depth_banks)
    if sequential_bits != expected_sequential_bits:
        raise RuntimeError("Group-buffer control and bank-selector widths differ")
    expected_instances = {"npu_top": 1, "compute_core": 1, "ws_systolic_array": 1,
                          "ws_systolic_cell": 256, "vector_engine": 1, "vector_pe": 16,
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
    from storage_geometry import inspect_selected_storage
    selected_storage = inspect_selected_storage(rows, memories, capacity, profile)
    return {
        "capacity_derivation": capacity,
        "implementation_profile": implementation_profile,
        "selected_storage": selected_storage,
        "module_instances": dict(sorted(instances.items())),
        "expected_compute_instances": expected_instances,
        "top_port_widths": top_widths,
        "group_buffer": {
            "path": group["path"], "lanes": 16, "rows": group_rows,
            "state_widths": group_state, "wrapper_port_widths": wrapper_widths,
            "macro_instances": len(macro_rows), "macro_type": macro_type,
            "macros_per_depth_bank": dict(sorted(bank_lanes.items())),
            "logical_storage_bits": 513 * group_rows,
            "physical_macro_storage_bits": len(macro_rows) * macro_depth * 16,
            "physical_macro_storage_bytes": len(macro_rows) * macro_depth * 16 // 8,
            "padding_bits": len(macro_rows) * macro_depth * 16 - 513 * group_rows,
            "capacity_utilization": 513 * group_rows / (len(macro_rows) * macro_depth * 16),
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
    parser.add_argument("--ia-compact-enable", type=int, choices=(0, 1), default=0)
    parser.add_argument("--implementation-profile", choices=tuple(PROFILES), default="current",
                        help="选择需要严格验证的存储实现：820c 或当前打包实现")
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys as yosys
        yosys.run_pass("script " + shlex.quote(str(args.worker)))
        return
    if args.out is None:
        parser.error("--out is required")
    root, out = args.source_root.resolve(), args.out.resolve()
    parameters = dict(PARAMETERS, IA_COMPACT_ENABLE=args.ia_compact_enable)
    wrapper_source = (root / "asic/rtl/smic40_sram_1r1w.sv").read_text()
    threshold = re.search(r"MACRO_DEPTH\s*=\s*\(DEPTH\s*<=\s*(\d+)\)", wrapper_source)
    if not threshold or int(threshold[1]) != PROFILES[args.implementation_profile]["wrapper_small_depth_limit"]:
        raise RuntimeError("SRAM selection threshold differs from the requested implementation profile")
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    snapshot = out / "snapshot"
    sources = input_files(root)
    input_paths = {str(path.relative_to(root)): path for path in sources}
    prepare_relative = "scripts/asic/prepare_dc_sources.py"
    prepare_source = root / prepare_relative
    if not prepare_source.is_file():
        prepare_source = ROOT / prepare_relative
    input_paths[prepare_relative] = prepare_source
    hashes = {relative: digest(path) for relative, path in input_paths.items()}
    # 冻结源码目录可独立于 Git；具体输入由文件摘要及源码清单摘要标识。
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                              capture_output=True)
    commit = revision.stdout.strip() if revision.returncode == 0 else None
    source_manifest = root / "manifest.json"
    for relative, path in input_paths.items():
        target = snapshot / relative
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
    options += ["-G" + name + "=" + str(value) for name, value in parameters.items()]
    options += ["-I" + path for path in includes]
    options += [str(path) for path in compilation_files]
    netlist, script, log = out / "npu.json", out / "elaborate.ys", out / "elaboration.log"
    script.write_text(" ".join(map(shlex.quote, options)) + "\n" +
                      "hierarchy -check -top npu_top\nproc\nopt_clean\nmemory_collect\ncheck -assert\n" +
                      "write_json " + shlex.quote(str(netlist)) + "\n")
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(script)]
    run(command, log, snapshot)
    design = json.loads(netlist.read_text())
    result = inspect(design, parameters, args.implementation_profile)
    unchanged = hashes == {relative: digest(path) for relative, path in input_paths.items()}
    if not unchanged:
        raise RuntimeError("Source inputs changed during complete NPU elaboration")
    result.update({
        "passed": True, "source_root": str(root), "source_commit": commit,
        "source_snapshot_manifest_sha256": digest(source_manifest) if source_manifest.is_file() else None,
        "input_source_paths": {relative: str(path) for relative, path in input_paths.items()},
        "source_sha256": hashes, "sources_unchanged": unchanged,
        "snapshot_sha256": {relative: digest(snapshot / relative) for relative in hashes},
        "prepared_source_sha256": {str(path.relative_to(prepared)): digest(path)
                                    for path in compilation_files if path.is_relative_to(prepared)},
        "prepare_script_sha256": hashes["scripts/asic/prepare_dc_sources.py"],
        "prepared_filelist_sha256": digest(prepared_filelist),
        "blackbox_source_sha256": digest(blackboxes),
        "checker_source_sha256": digest(Path(__file__).resolve()),
        "storage_analyzer_sha256": digest(HERE / "storage_geometry.py"),
        "elaboration_script_sha256": digest(script), "elaborated_netlist_sha256": digest(netlist),
        "tool": design.get("creator", "Yosys with Slang"),
        "structural_frontend": "Yosys read_slang --keep-hierarchy",
        "defines": DEFINES, "parameters": parameters,
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
