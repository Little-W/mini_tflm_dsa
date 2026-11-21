#!/usr/bin/env python3
"""比较行为级算术资源选择前后的完整模块状态与公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "linear_dma": {
        "source": "rtl/npu/dma/axi_linear_block_dma.sv", "top": "axi_linear_block_dma",
        "profiles": [
            {"SIZE": 4, "BUS_WIDTH": 32, "DATA_WIDTH": 8, "RD_CONTEXT_DEPTH": 1},
            {"SIZE": 16, "BUS_WIDTH": 32, "DATA_WIDTH": 16, "RD_CONTEXT_DEPTH": 4},
            {"SIZE": 16, "BUS_WIDTH": 64, "DATA_WIDTH": 16, "RD_CONTEXT_DEPTH": 4},
            {"SIZE": 16, "BUS_WIDTH": 128, "DATA_WIDTH": 16, "RD_CONTEXT_DEPTH": 4},
            {"SIZE": 16, "BUS_WIDTH": 64, "DATA_WIDTH": 32, "RD_CONTEXT_DEPTH": 2},
            {"SIZE": 64, "BUS_WIDTH": 64, "DATA_WIDTH": 16, "RD_CONTEXT_DEPTH": 4,
             "CACHE_BLOCKS": 64}],
    },
    "oa_writer": {
        "source": "rtl/npu/writeback/oa_writer.sv", "top": "oa_writer",
        "profiles": [{"VLEN": n, "BUS_WIDTH": b, "COUNT_WIDTH": c}
                     for n, b, c in [(4, 32, 4), (16, 64, 16), (16, 64, 32), (32, 64, 32)]],
    },
    "bias_control": {
        "source": "rtl/npu/loaders/bias_loader_ctrl.sv", "top": "bias_loader_ctrl",
        "profiles": [{"SIZE": n, "BUS_WIDTH": b, "COUNT_WIDTH": c, "GROUP_BLOCKS_MAX": g}
                     for n, b, c, g in [(4, 32, 8, 1), (16, 64, 16, 4),
                                       (16, 64, 32, 32), (32, 64, 32, 64)]],
    },
    "read_guard": {
        "source": "rtl/npu/conv/conv_axi_read_guard.sv", "top": "conv_axi_read_guard",
        "profiles": [{"ADDR_W": a, "DATA_W": d, "SPLIT_GEMM_4K": s}
                     for a, d, s in [(32, 32, 0), (32, 32, 1), (32, 64, 0),
                                     (32, 64, 1), (16, 16, 1), (33, 128, 1), (40, 256, 1)]],
    },
    "requant_buffer": {
        "source": "rtl/npu/writeback/requant_group_buffer.sv", "top": "requant_group_buffer",
        "abstract_ram": True,
        "profiles": [{"p_rows": rows, "p_lanes": 16}
                     for rows in (1, 3, 127, 128, 512, 513, 1024)],
    },
}
HELPERS = ["rtl/common/regfile.v", "rtl/common/add_equal.sv",
           "rtl/common/parallel_prefix_add.sv", "rtl/common/unsigned_compare.sv"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe_ram(text):
    """为两侧提供相同任意读取数据，并比较实际存储的全部读写端口。"""
    ports = """input wire logic i_output_valid,
    input wire logic [32*p_lanes:0] formal_ram_read_data,
    output wire logic [32*p_lanes:0] formal_ram_write_data,
    output wire logic [31:0] formal_ram_read_addr, formal_ram_write_addr,
    output wire logic formal_ram_read_en, formal_ram_write_en, formal_ram_write_mask
);"""
    text, count = re.subn(r"input\s+wire\s+logic\s+i_output_valid\s*\n\);", ports, text)
    if count != 1:
        raise ValueError("无法定位量化缓冲端口")
    connections = """assign storage_o_rd_data = formal_ram_read_data;
    assign formal_ram_write_data = storage_i_wr_data;
    assign formal_ram_read_addr = 32'(storage_i_rd_addr);
    assign formal_ram_write_addr = 32'(storage_i_wr_addr);
    assign formal_ram_read_en = storage_i_rd_en;
    assign formal_ram_write_en = storage_i_wr_en;
    assign formal_ram_write_mask = storage_i_wr_mask;"""
    text, count = re.subn(r"`ifdef ASIC_SRAM\b.*?`endif", connections, text, flags=re.S)
    if count != 1:
        raise ValueError("无法定位量化缓冲存储实例")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="0097b66e")
    parser.add_argument("--cases", nargs="+", choices=list(CASES), default=list(CASES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helpers = []
    hashes = {}
    for name in HELPERS:
        path = ROOT / name
        snapshot = out / path.name
        snapshot.write_bytes(path.read_bytes())
        helpers.append(snapshot)
        hashes[name] = digest(path)
    report = {"passed": False, "reference": args.reference, "inputs_constrained": False,
              "source_sha256": hashes, "cases": []}
    for name in args.cases:
        case = CASES[name]
        folder = out / name
        folder.mkdir(exist_ok=True)
        current = ROOT / case["source"]
        hashes[case["source"]] = digest(current)
        snapshots = {"current": folder / "current.sv", "reference": folder / "reference.sv"}
        texts = {"current": current.read_text(), "reference": subprocess.check_output(
            ["git", "show", args.reference + ":" + case["source"]], cwd=ROOT, text=True)}
        for label, text in texts.items():
            snapshots[label].write_text(observe_ram(text) if case.get("abstract_ram") else text)
        entry = {"name": name, "source": case["source"],
                 "reference_sha256": hashlib.sha256(texts["reference"].encode()).hexdigest(),
                 "arbitrary_memory_read_data": bool(case.get("abstract_ram")),
                 "complete_memory_ports_compared": bool(case.get("abstract_ram")), "profiles": []}
        for index, parameters in enumerate(case["profiles"]):
            commands = []
            for label, path in snapshots.items():
                options = [f"-G{key}={value}" for key, value in parameters.items()]
                commands += ["read_slang --top " + case["top"] +
                             " -D SYNTHESIS=1 -D XILINX_FPGA=1 " +
                             shlex.join([*options, str(path), *map(str, helpers)]),
                             "prep -top " + case["top"] + " -flatten", "memory_map",
                             "async2sync", "opt_clean", "rename " + case["top"] + " " + label,
                             "design -stash " + label]
            commands += ["design -copy-from reference -as reference reference",
                         "design -copy-from current -as current current",
                         "equiv_make reference current equivalent", "hierarchy -top equivalent",
                         "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2",
                         "equiv_status -assert"]
            script, log = folder / f"profile{index}.ys", folder / f"profile{index}.log"
            script.write_text("\n".join(commands) + "\n")
            with log.open("w") as stream:
                subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                               cwd=ROOT, check=True, timeout=240)
            result = log.read_text()
            bits = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", result)
            if bits is None or int(bits[2]) or "Equivalence successfully proven" not in result:
                raise RuntimeError("完整模块等价检查未完成：" + str(log))
            row = {"parameters": parameters, "passed": True,
                   "equivalent_bits": int(bits[1]), "log_sha256": digest(log)}
            entry["profiles"].append(row)
            print(json.dumps({"name": name, **row}), flush=True)
        report["cases"].append(entry)
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
