#!/usr/bin/env python3
"""核对固定比较配置中的每周期有效 INT8 乘加数量。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def module_bodies(text):
    return dict(re.findall(r"^module\s+(\w+)\b(.*?)^endmodule\b", text,
                           flags=re.MULTILINE | re.DOTALL))


def instances(body, module):
    return len(re.findall(r"^\s*" + re.escape(module) + r"\s+\w+\s*\(",
                          body, flags=re.MULTILINE))


def reachable_counts(modules, top):
    expression = re.compile(r"^\s*(" + "|".join(map(re.escape, modules)) +
                            r")\s+\w+\s*\(", re.MULTILINE)
    cache = {}

    def visit(name, active):
        if name in active:
            raise ValueError("Recursive module hierarchy: " + name)
        if name not in cache:
            result = Counter({name: 1})
            for child in expression.findall(modules[name]):
                result.update(visit(child, active | {name}))
            cache[name] = result
        return cache[name]

    return dict(visit(top, set()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npu", type=Path, required=True)
    parser.add_argument("--npu-profile", type=Path, required=True)
    parser.add_argument("--gemmini-generated", type=Path, required=True)
    parser.add_argument("--public-work", type=Path, required=True)
    parser.add_argument("--nvdla-generated", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = {}

    def read(path):
        path = path.resolve()
        data = path.read_bytes()
        sources[str(path)] = hashlib.sha256(data).hexdigest()
        return data.decode()

    profile = json.loads(read(args.npu_profile))
    profile = profile.get("hardware_profile", profile.get("profile", profile))
    size, vector = profile["size"], profile["vector_pe_count"]
    assert size == 16 and vector == 16 and profile["bus_width"] == 64
    array = read(args.npu / "rtl/npu/compute/ws_systolic_array.sv")
    cell = read(args.npu / "rtl/npu/compute/ws_systolic_cell.sv")
    top = read(args.npu / "rtl/npu/top/npu_top.sv")
    matrix = read(args.npu / "rtl/npu/top/npu_matrix_engine.sv")
    vector_rtl = read(args.npu / "rtl/npu/conv/vector_engine.sv")
    assert re.search(r"for\s*\(genvar row=0; row<SIZE; row\+\+\)", array)
    assert re.search(r"for\s*\(genvar column=0; column<SIZE; column\+\+\)", array)
    assert "assign mac_result = data_reg * selected_weight + sum_reg;" in cell
    assert "cfg_start_event = i_calc_start && i_sa_ready && !i_cfg_vector_enable" in matrix
    assert re.search(r"vector_start_fire\s*=.*?cfg_vector_enable && !cfg_conv_enable;", top, re.S)
    assert "task_accept_conditions = !run_vector && !vector_rejected && vector_engine_ready &&" in top
    assert "for (genvar lane = 0; lane < PE_COUNT; lane++)" in vector_rtl

    gemmini = module_bodies(read(args.gemmini_generated / "GemminiCompare.v"))
    params = read(args.gemmini_generated / "gemmini_params.h")
    dim = int(re.search(r"^#define DIM (\d+)$", params, re.M)[1])
    gemmini_tiles = instances(gemmini["Mesh"], "Tile")
    gemmini_cells = instances(gemmini["Tile"], "PE_256")
    assert dim == 16 and gemmini_tiles == dim * dim and gemmini_cells == 1
    assert "typedef int8_t elem_t;" in params
    assert "io_in_control_dataflow" in gemmini["PE_256"]
    assert "assign io_out_b = ~io_in_control_dataflow" in gemmini["PE_256"]

    vta = module_bodies(read(args.public_work / "tvm-vta/build/bench80k/VTA.Bench80K.sv"))
    vta_counts = reachable_counts(vta, "VTAShell")
    vta_config = read(args.public_work / "tvm-vta/hardware/chisel/src/main/scala/vta/Bench80K.scala")
    assert "batch = 1, blockOut = 16, blockOutFactor = 1, blockIn = 16" in vta_config
    assert vta_counts["DotProduct"] == 16 and vta_counts["MAC"] == 256
    assert instances(vta["DotProduct"], "MAC") == 16

    coral = args.public_work / "coralnpu"
    flags = read(coral / "hdl/chisel/src/coralnpu/flags.bzl")
    defines = read(coral / "hdl/verilog/rvv/inc/rvv_backend_define.svh")
    pe_array = read(coral / "hdl/verilog/rvv/design/Zvt/zvt_pe_array.sv")
    pe_block = read(coral / "hdl/verilog/rvv/design/Zvt/zvt_pe_block.sv")
    pe_lane = read(coral / "hdl/verilog/rvv/design/Zvt/zvt_pe_mulbulk_int_lane.sv")
    configuration = json.loads(read(args.public_work / "coral_benchmark/coral_configuration.json"))["configuration"]
    assert configuration["vector_bits"] == 128 and "VLEN_128" in flags
    assert re.search(r"`define\s+NUM_BLK\s+4\b", defines)
    assert "`define NUM_PE              (`TE*`TE*`COMPRATIO)" in defines
    assert "`define COMPRATIO         4/`TE" in defines
    assert "for(genvar i=0; i<`TE/2*`COMPRATIO; i++)" in pe_block
    assert "for(genvar j=0; j<`TE/2; j++)" in pe_block
    assert "parameter int unsigned             WIDTH = 32" in pe_lane
    assert "(i == j)" in pe_lane and "gen_int8_tree4" in pe_lane
    assert "zvt_pe_block" in pe_array
    coral_units = 4 * (16 // 2 * 4 // 16) * (16 // 2)
    coral_products = 32 // 8
    assert coral_units == configuration["physical_dot_product_units"] == 64
    assert coral_products == configuration["int8_products_per_dot"] == 4

    project = read(args.nvdla_generated / "spec/defs/project.vh")
    def macro(name):
        return int(re.search(r"^`define\s+" + name + r"\s+(\d+)\s*$", project, re.M)[1])
    atomic_c, atomic_k = macro("NVDLA_MAC_ATOMIC_C_SIZE"), macro("NVDLA_MAC_ATOMIC_K_SIZE")
    assert atomic_c == 32 and atomic_k == 8 and macro("NVDLA_PRIMARY_MEMIF_WIDTH") == 64

    rows = [
        {"implementation": "NPU", "physical_compute_units": size * size,
         "int8_macs_per_unit_per_cycle": 1, "int8_macs_per_cycle": size * size,
         "vector_units": vector, "depthwise_macs_per_cycle": vector,
         "active_engine_selection": "Matrix and vector launch conditions are mutually exclusive; a new task waits for both engines to be ready."},
        {"implementation": "Gemmini-BiRD", "physical_compute_units": gemmini_tiles * gemmini_cells,
         "int8_macs_per_unit_per_cycle": 1, "int8_macs_per_cycle": dim * dim,
         "generated_hierarchy": "Mesh: 256 Tile instances; each Tile: one PE_256 instance; PE dataflow selects one MAC result."},
        {"implementation": "VTA", "physical_compute_units": vta_counts["MAC"],
         "int8_macs_per_unit_per_cycle": 1, "int8_macs_per_cycle": vta_counts["MAC"],
         "generated_hierarchy": "VTAShell: 16 DotProduct instances, each containing 16 MAC instances."},
        {"implementation": "Coral NPU VME", "physical_compute_units": coral_units,
         "int8_macs_per_unit_per_cycle": coral_products, "int8_macs_per_cycle": coral_units * coral_products,
         "generated_configuration": "VLEN=128, four PE blocks, two rows and eight columns of dot-product units per block, four INT8 diagonal products per unit."},
        {"implementation": "NVDLA nv_small_256", "physical_compute_units": atomic_c * atomic_k,
         "int8_macs_per_unit_per_cycle": 1, "int8_macs_per_cycle": atomic_c * atomic_k,
         "atomic_c": atomic_c, "atomic_k": atomic_k},
    ]
    for row in rows:
        assert row["int8_macs_per_cycle"] == 256
        row["equivalent_int8_pe_limit"] = 256
        row["compute_scaling_factor"] = 1.0
    report = {"passed": True,
              "definition": "One equivalent INT8 PE can complete one effective INT8 multiplication and its accumulation per cycle. One MAC counts as two arithmetic operations.",
              "target_int8_macs_per_cycle": 256,
              "comparison": "Measured cycles with the listed compute configurations. No cycle scaling is applied.",
              "implementations": rows, "sources_sha256": sources}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "implementations": len(rows),
                      "target_int8_macs_per_cycle": 256, "source_files": len(sources)}))


if __name__ == "__main__":
    main()
