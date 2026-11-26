#!/usr/bin/env python3
"""证明真实 RAM 的全部内容及返回数据只使用已启用的写入字节。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from run_formal import ROOT, digest

PROFILES = {
    "ia_bank": ("regfile", 512, 9),
    "shared_segment": ("ia_ps_role_ram", 128, 7),
    "regfile_invalid": ("regfile", 3, 3),
    "shared_invalid": ("ia_ps_role_ram", 3, 3),
}


def wrapper(module, depth, address_width, variant):
    common = f"""// 保留实际存储器的完整数组与时序，未启用字节使用独立自由数据。
module storage_proof (
 input wire logic clk,
 input wire logic access_enable, write_enable, read_enable,
 input wire logic [{address_width-1}:0] write_address, read_address,
 input wire logic [127:0] write_data, unwritten_data,
 input wire logic [15:0] write_mask,
 input wire logic second_write, second_read, first_read_allowed,
 input wire logic [127:0] second_data,
 output logic [127:0] first_return, second_return);
 logic [127:0] {variant}_write_data;
"""
    if variant == "reference":
        common += f" assign {variant}_write_data = write_data;\n"
    else:
        common += f""" for(genvar byte_index=0;byte_index<16;byte_index++) begin:g_byte
 assign {variant}_write_data[8*byte_index+:8] = write_mask[byte_index] ?
     write_data[8*byte_index+:8] : unwritten_data[8*byte_index+:8];
 end
"""
    if module == "regfile":
        common += f""" regfile #(.p_data_width(128),.p_depth({depth}),.p_addr_width({address_width}),
 .p_write_unit(8),.p_read_ports(1),.p_sync_read(1'b1)) u_ram (
 .clk(clk),.i_wr_en(write_enable),.i_wr_addr(write_address),
 .i_wr_data({variant}_write_data),.i_wr_mask(write_mask),
 .i_rd_en(read_enable),.i_rd_addr(read_address),.o_rd_data(first_return));
 assign second_return = '0;
"""
    else:
        common += f""" ia_ps_role_ram #(.p_depth({depth}),.p_addr_width({address_width})) u_ram (
 .clk(clk),.i_access_enable(access_enable),.i_a_enable(read_enable),
 .i_a_read_allowed(first_read_allowed),.i_a_write(write_enable),
 .i_a_addr(write_address),.i_a_data({variant}_write_data),.i_a_mask(write_mask),
 .o_a_data(first_return),.i_b_enable(second_read),.i_b_write(second_write),
 .i_b_addr(read_address),.i_b_data(second_data),.o_b_data(second_return));
"""
    return common + "endmodule\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {"regfile": ROOT / "rtl/common/regfile.v",
               "ia_ps_role_ram": ROOT / "rtl/npu/buffers/ia_ps_role_ram.sv"}
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources.values()}
    rows = []
    for name in args.profiles:
        module, depth, address_width = PROFILES[name]
        commands = []
        for variant in ("reference", "candidate"):
            path = out / (name + "_" + variant + ".sv")
            path.write_text(wrapper(module, depth, address_width, variant))
            commands += ["read_slang --top storage_proof -USYNTHESIS -UXILINX_FPGA " +
                         shlex.join([str(path), str(sources[module])]),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top storage_proof -flatten", "memory_map", "opt_clean",
                         "rename storage_proof " + variant, "design -stash " + variant]
        blacklist = out / (name + "_data_ports.txt")
        blacklist.write_text("u_ram.i_wr_data\nu_ram.i_a_data\n")
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from candidate -as candidate candidate",
                     "equiv_make -blacklist " + shlex.quote(str(blacklist)) +
                     " reference candidate proof", "hierarchy -top proof",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2",
                     "equiv_status -assert"]
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=600)
        text = log.read_text()
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", text)
        if not match or int(match[2]) or "Equivalence successfully proven!" not in text:
            raise RuntimeError("实际 RAM 写字节性质未完成：" + name)
        row = dict(profile=name, module=module, depth=depth, address_width=address_width,
                   passed=True, all_array_words_compared=True, all_read_outputs_compared=True,
                   arbitrary_unwritten_bytes=True, input_constraints=None,
                   proven_bits=int(match[1]), script_sha256=digest(script), log_sha256=digest(log))
        rows.append(row)
        print(json.dumps(row), flush=True)
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("RAM 证明期间源码发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, source_sha256=hashes,
        runner_sha256=digest(__file__), profiles=rows,
        proven_bits=sum(row["proven_bits"] for row in rows)), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
