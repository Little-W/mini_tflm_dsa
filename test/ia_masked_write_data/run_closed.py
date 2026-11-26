#!/usr/bin/env python3
"""检查 IA 缓存写入端与真实共享存储的全部命令、数组及消费者输出。"""
from __future__ import annotations

import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from run_formal import ROOT, REFERENCE, CACHE, digest, original, port_declarations
sys.path.insert(0, str(ROOT))
from scripts.rtl.source_files import input_files, with_dependencies

CHANNEL = Path("rtl/npu/buffers/ia_ps_channel_ram.sv")
PROFILES = [(0, 8), (1, 8), (1, 4)]


def channel_text(abstract):
    location = ROOT / "test/ps_shared_read_control/run_shared.py"
    spec = spec_from_file_location("shared_reference_checks", location)
    support = module_from_spec(spec)
    spec.loader.exec_module(support)
    text = support.instrument((ROOT / CHANNEL).read_text(), "current", abstract)
    text = text.replace("channel_current", "channel_core")
    if abstract:
        text += support.MODELS
    return text


def wrapper(source, variant, abstract):
    ports = port_declarations(source)
    header = source.split(") (", 1)[0]
    header = header.replace("module ia_loader_cache_mgr #(", "module closed_storage #(", 1)
    # 存储容量采用当前生产的 7 个 8 KiB 物理块。
    inputs = [(direction, kind, name, unpacked) for direction, kind, name, unpacked in ports
              if direction == "input" and name != "ram_port_rd_data"]
    outputs = [(direction, kind, name, unpacked) for direction, kind, name, unpacked in ports
               if direction == "output" and name not in ("ram_port_wr_data", "ram_shared_wr_data")]
    declared = [f"{direction} {kind} {name} {unpacked}" for direction, kind, name, unpacked in inputs + outputs]
    declared += ["input wire logic access_enable, configure", "input wire logic [2:0] ia_banks",
                 "input wire logic [3:0] ps_read_enable, ps_write_enable",
                 "input wire logic [RAM_WORD_ADDR_WIDTH-1:0] ps_read_address[4], ps_write_address[4]",
                 "input wire logic [127:0] ps_write_data[4]",
                 "input wire logic [16:0][255:0] proof_words",
                 "output logic capacity_fault", "output logic [127:0] ia_return[2], ps_return[4]",
                 "output logic [319:0] command_observation[9]"]
    text = header + ") (\n" + ",\n".join(declared) + "\n);\n"
    text += "logic [127:0] cache_write_words[2], cache_shared_word;\n"
    parameters = re.findall(r"\bparameter\s+(?:int\s+unsigned|int|bit|integer)\s+(\w+)\s*=",
                            source.split(") (", 1)[0])
    parameters = [name for name in parameters if name != "p_zero_masked_write_data"]
    assignments = [f".{name}({name})" for name in parameters]
    if variant == "candidate":
        assignments.append(".p_zero_masked_write_data(1'b0)")
    module = "ia_loader_cache_mgr_reference" if variant == "reference" else "ia_loader_cache_mgr"
    text += module + " #(" + ",".join(assignments) + ") u_cache_mgr (\n"
    connections = []
    for _, _, name, _ in ports:
        value = {"ram_port_wr_data": "cache_write_words", "ram_shared_wr_data": "cache_shared_word",
                 "ram_port_rd_data": "ia_return"}.get(name, name)
        connections.append("." + name + "(" + value + ")")
    text += ",".join(connections) + ");\n"
    text += """channel_core #(.p_shared_write_stage(1'b1),.p_ia_nonempty_writes(1'b1),
 .p_paired_ia_ports(1'b1),.p_allow_inactive_return_updates(1'b1),
 .p_bank_bytes(8192),.p_total_bytes(57344),.p_addr_width(RAM_WORD_ADDR_WIDTH),
 .p_bank_count_width(3)) u_channel (
 .clk(clk),.rst_n(rst_n),.i_access_enable(access_enable),.i_cfg_valid(configure),
 .i_cfg_ia_banks(ia_banks),.o_capacity_fault(capacity_fault),
 .i_ia_read_en(ram_port_rd_en),.i_ia_write_en(ram_port_wr_en),
 .i_ia_read_addr(ram_port_rd_addr),.i_ia_write_addr(ram_port_wr_addr),
 .o_ia_read_data(ia_return),.i_ia_write_data(cache_write_words),
 .i_ia_shared_write_data(cache_shared_word),.i_ia_write_mask(ram_port_wr_mask),
 .i_ps_read_en(ps_read_enable),.i_ps_write_en(ps_write_enable),
 .i_ps_read_addr(ps_read_address),.i_ps_write_addr(ps_write_address),
 .o_ps_read_data(ps_return),.i_ps_write_data(ps_write_data)"""
    text += ",.proof_words(proof_words));\n" if abstract else ");\n"
    text += """function automatic logic [127:0] enabled_bytes(input logic [127:0] value,input logic [15:0] mask);
 for(int byte_index=0;byte_index<16;byte_index++)
   enabled_bytes[8*byte_index+:8]=value[8*byte_index+:8] & {8{mask[byte_index]}};
endfunction
"""
    def observe(path, index, role=False):
        if role:
            terms = ["i_access_enable", "i_a_enable && " + path + ".i_a_read_allowed", "i_a_write",
                     "i_a_addr", "i_a_mask"]
            expression = [path + "." + field for field in terms]
            expression += [f"enabled_bytes({path}.i_a_data,{path}.i_a_mask & "
                           f"{{16{{{path}.i_access_enable && {path}.i_a_write}}}})"]
            expression += [path + "." + field for field in ("i_b_enable", "i_b_write", "i_b_addr", "i_b_data")]
        else:
            expression = [path + "." + field for field in ("i_wr_en", "i_rd_en", "i_wr_addr", "i_rd_addr", "i_wr_mask")]
            expression += [f"enabled_bytes({path}.i_wr_data,{path}.i_wr_mask & {{16{{{path}.i_wr_en}}}})"]
        return f"assign command_observation[{index}]=320'({{{','.join(expression)}}});\n"
    text += observe("u_channel.u_ia_ram", "0")
    text += "for(genvar channel=0;channel<4;channel++)begin:g_memory_commands\n"
    text += observe("u_channel.g_fixed_channel[channel].u_ram", "5+channel")
    text += "`ifdef XILINX_FPGA\n"
    text += observe("u_channel.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram", "1+channel", True)
    text += "`else\n"
    text += observe("u_channel.g_shared_bank[1].g_channel[channel].g_held_response.u_ram", "1+channel")
    text += "`endif\nend\nendmodule\n"
    return text


def execute(command, log, timeout=480):
    with log.open("w") as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--modes", nargs="+", choices=("generic", "fpga"), default=("generic", "fpga"))
    parser.add_argument("--profiles", nargs="+", type=int, choices=range(len(PROFILES)), default=list(range(len(PROFILES))))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current, reference = (ROOT / CACHE).read_text(), original(CACHE, args.reference)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in input_files(
        with_dependencies([ROOT / CACHE, ROOT / CHANNEL], ROOT), ROOT)}
    channel = out / "channel_core.sv"
    channel.write_text(channel_text(True))
    original_cache = out / "ia_loader_cache_mgr_reference.sv"
    original_cache.write_text(reference.replace("module ia_loader_cache_mgr #(",
                                               "module ia_loader_cache_mgr_reference #(", 1))
    records = []
    for mode in args.modes:
        flags = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if mode == "fpga" else ["-USYNTHESIS", "-UXILINX_FPGA"]
        for profile in args.profiles:
            compact, lanes = PROFILES[profile]
            label = f"{mode}_compact{compact}_lanes{lanes}"
            parameters = dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=lanes*8, DMA_LANES=lanes,
                              CACHE_BLOCKS=32, COMPACT_S8=compact, RAM_WORD_ADDR_WIDTH=12,
                              p_dma_source_layout=1, p_shared_write_stage=1,
                              p_precomputed_slot_mask=1, p_indexed_slot_rows=1)
            commands = []
            for variant in ("reference", "candidate"):
                path = out / (label + "_" + variant + ".sv")
                path.write_text(wrapper(current, variant, True))
                sources = with_dependencies([path, channel, original_cache, ROOT / CACHE], ROOT)
                commands += ["read_slang --top closed_storage " + shlex.join(flags +
                    [f"-G{key}={value}" for key, value in parameters.items()] + list(map(str, sources))),
                    "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                    "prep -top closed_storage -flatten", "memory_map", "async2sync", "opt_clean",
                    "rename closed_storage " + variant, "design -stash " + variant]
            excluded = out / (label + "_write_data_interfaces.txt")
            # 写数据在命令观察输出中按实际字节资格检查；全部控制、地址和掩码保留比较。
            data_interfaces = ["cache_write_words", "cache_shared_word",
                "u_cache_mgr.ram_port_wr_data", "u_cache_mgr.ram_shared_wr_data",
                "u_channel.i_ia_write_data", "u_channel.i_ia_shared_write_data",
                "u_channel.ia_bank_write_data", "u_channel.ia_ram_i_wr_data",
                "u_channel.u_ia_ram.i_wr_data"]
            for channel_index in range(4):
                prefix = f"u_channel.g_shared_bank[1].g_channel[{channel_index}]"
                data_interfaces += [prefix + ".ram_i_wr_data",
                    prefix + ".g_qualified_response.ia_write_data",
                    prefix + ".g_qualified_response.u_ram.i_a_data",
                    prefix + ".g_held_response.u_ram.i_wr_data"]
            excluded.write_text("\n".join(data_interfaces) + "\n")
            commands += ["design -copy-from reference -as reference reference",
                         "design -copy-from candidate -as candidate candidate",
                         "equiv_make -blacklist " + shlex.quote(str(excluded)) + " reference candidate proof",
                         "hierarchy -top proof", "equiv_simple -seq 1", "opt_clean",
                         "equiv_induct -seq 4", "equiv_status -assert"]
            script, log = out / (label + ".ys"), out / (label + ".log")
            script.write_text("\n".join(commands) + "\n")
            result = execute([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
            match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", result)
            if not match or int(match[2]) or "Equivalence successfully proven!" not in result:
                raise RuntimeError("IA 与共享存储的完整连接证明未完成：" + label)
            record = dict(mode=mode, parameters=parameters, passed=True, input_constraints=None,
                          all_physical_commands=True, all_enabled_memory_bytes=True,
                          all_consumer_outputs=True, proven_bits=int(match[1]),
                          script_sha256=digest(script), log_sha256=digest(log))
            records.append(record)
            print(json.dumps(record), flush=True)
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("存储连接证明期间源码发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, runner_sha256=digest(__file__), profiles=records,
        proven_bits=sum(row["proven_bits"] for row in records)), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
