#!/usr/bin/env python3
"""证明实际缓存返回逻辑的组合等价和完整小规模缓存的逐周期等价。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from support import ROOT, SOURCE, REFERENCE, check_sources, digest, prepare_inputs
from selection import prove as prove_selection

PARAMETERS = ("parameter integer WAYS=2,READ_WIDTH=32,DEMAND_DEPTH=1,LB=4,SI=7,"
              "WI=WAYS==1?1:$clog2(WAYS),DQ_CW=$clog2(DEMAND_DEPTH+1)")
PORTS = """input logic [1:0] fg_state,
input logic configured,clearing,bypass_q,lookup_snapshot_valid,
input logic work_word_matches_q,demand_word_matches_q,
input logic [SI-1:0] lookup_snapshot_set,work_set,demand_set,demand_fill_set,
input logic work_valid,work_range,demand_range,demand_filled,response_error,
input logic [DQ_CW-1:0] response_count,
input logic [31:0] work_address,demand_addr,
input logic [WI-1:0] demand_fill_way,
input logic [WAYS-1:0] valid_lookup,
input logic [WAYS-1:0][31:LB] lookup_tag,
input logic [WAYS-1:0][READ_WIDTH-1:0] input_data,
input logic [READ_WIDTH-1:0] ram_rdata"""
NAMES = ("fg_state", "configured", "clearing", "bypass_q", "lookup_snapshot_valid",
         "work_word_matches_q", "demand_word_matches_q", "lookup_snapshot_set", "work_set",
         "demand_set", "demand_fill_set", "work_valid", "work_range", "demand_range", "demand_filled",
         "response_error", "response_count", "work_address", "demand_addr", "demand_fill_way",
         "valid_lookup", "lookup_tag", "input_data", "ram_rdata")


def assignment(source, name):
    match = re.search(r"  assign " + name + r"\s*=\s*.*?;", source, re.S)
    if match is None:
        raise RuntimeError("找不到实际信号表达式: " + name)
    return match[0]


def response_model(name, source, payload_when_valid=False):
    first = source.index("  always_comb begin\n    lookup_hit=0;lookup_way=0;")
    end = source.index("  always_comb begin\n    pf_hit_raw", first)
    lookup = source[first:end]
    first = source.index(";", source.index("  assign request_pop=")) + 1
    end = source.index("  assign core_rsp_ready", first)
    response = source[first:end]
    model = f"module {name} #({PARAMETERS})(\n{PORTS},output logic [READ_WIDTH+3:0] observed);\n"
    model += """localparam logic [1:0] FG_IDLE=0,FG_MISS=1,FG_RESP=2;
typedef struct packed {logic [31:0] address; logic [SI-1:0] set_index;} request_t;
request_t work_request;
logic work_ready,req_fire,lookup_ready,lookup_range,lookup_hit,work_lookup_ready,demand_lookup_ready;
logic [WI-1:0] lookup_way;
logic [WAYS-1:0] fast_hits;
logic [READ_WIDTH-1:0] fast_hit_data,core_rsp_data;
logic [READ_WIDTH-1:0] speculative_data[WAYS];
logic fast_hit_response,core_rsp_valid,core_rsp_error;
assign work_request.address=work_address;
assign work_request.set_index=work_set;
for(genvar way=0;way<WAYS;way++) begin:g_data
  assign speculative_data[way]=input_data[way];
end
"""
    model += "\n".join(assignment(source, signal) for signal in
                       ("work_lookup_ready", "demand_lookup_ready", "work_ready", "req_fire",
                        "lookup_ready", "lookup_range"))
    payload = "(core_rsp_valid ? core_rsp_data : {READ_WIDTH{1'b0}})" if payload_when_valid else "core_rsp_data"
    return model + "\n" + lookup + "\n" + response + f"""
assign observed={{req_fire,fast_hit_response,core_rsp_valid,core_rsp_error,{payload}}};
endmodule
"""


def execute(script, log, expected):
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=360)
    if expected not in log.read_text():
        raise RuntimeError("等价证明没有完成: " + str(log))


def prove_response(out, paths, payload_when_valid=False, profiles=None):
    text = "".join(response_model(label, path.read_text(), payload_when_valid) for label, path in paths.items())
    text += f"module comparison #({PARAMETERS})(\n{PORTS},output logic equivalent);\n"
    text += "logic [READ_WIDTH+3:0] expected,actual;\n"
    connections = ",".join(f".{name}({name})" for name in NAMES)
    for label, result in (("reference", "expected"), ("current", "actual")):
        text += f"{label} #(.WAYS(WAYS),.READ_WIDTH(READ_WIDTH),.DEMAND_DEPTH(DEMAND_DEPTH),.LB(LB)) "
        text += f"u_{label}({connections},.observed({result}));\n"
    text += "assign equivalent=expected==actual;\nendmodule\n"
    source = out / "response_comparison.sv"
    source.write_text(text)
    results = []
    if profiles is None:
        profiles = ((1,32,1,4), (2,32,1,4), (2,32,4,4),
                    (2,64,1,4), (2,64,4,4), (3,64,8,5), (4,128,8,5),
                    (3,64,1,5), (4,128,1,5),
                    (2,64,1,7), (2,64,4,7))
    for ways, width, depth, lb in profiles:
        name = f"response_w{ways}_r{width}_d{depth}_l{lb}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text(f"read_slang --top comparison -GWAYS={ways} -GREAD_WIDTH={width} "
            f"-GDEMAND_DEPTH={depth} -GLB={lb} " + shlex.quote(str(source)) +
            "\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        execute(script, log, "SUCCESS!")
        results.append(dict(WAYS=ways, READ_WIDTH=width, DEMAND_DEPTH=depth, LB=lb,
                            passed=True, log_sha256=digest(log)))
        print("CACHE_RESPONSE_EQUIVALENCE_PASS", name, flush=True)
    return results


def observed_cache(source, label, payload_when_valid=False):
    first = source.index("module conv_windowed_cache")
    end = source.index("endmodule", first)
    body = source[first:end]
    marker = "  input logic [31:0] prefetch_ref_epoch = 32'd0);"
    if body.count(marker) != 1:
        raise RuntimeError("无法唯一识别窗口缓存端口")
    body = body.replace(marker, """  input logic [31:0] prefetch_ref_epoch = 32'd0,
  output logic [130+SI:0] formal_work_state, formal_lookup_state, formal_incoming_state,
  output logic [DEMAND_DEPTH*(131+SI)-1:0] formal_queue_state);""")
    body += "\nassign formal_work_state=work_request;\n"
    body += "assign formal_lookup_state=lookup_read_request;\n"
    body += "assign formal_incoming_state=incoming_request;\n"
    body += "for(genvar slot=0;slot<DEMAND_DEPTH;slot++) begin:g_formal_queue\n"
    body += "  assign formal_queue_state[slot*(131+SI)+:(131+SI)]=request_queue[slot];\nend\n"
    if payload_when_valid:
        body = body.replace("  output logic [DEMAND_DEPTH*(131+SI)-1:0] formal_queue_state);", """  output logic [DEMAND_DEPTH*(131+SI)-1:0] formal_queue_state,
  output logic formal_response_push,
  output logic [READ_WIDTH-1:0] formal_saved_payload);""")
        port_end = body.index(");") + 2
        payload_name = "formal_" + label + "_raw_rsp_data"
        core_name = "formal_" + label + "_core_rsp_data"
        logic = re.sub(r"(?<!\.)\brsp_data\b", payload_name, body[port_end:])
        logic = re.sub(r"\bcore_rsp_data\b", core_name, logic)
        logic = re.sub(r"\bfast_hit_data\b", "formal_" + label + "_fast_hit_data", logic)
        body = body[:port_end] + f"\nlogic [READ_WIDTH-1:0] {payload_name};\n" + logic
        body += f"\nassign rsp_data = rsp_valid ? {payload_name} : '0;\n"
        body += "assign formal_response_push = response_push;\n"
        body += f"assign formal_saved_payload = response_push ? {core_name} : '0;\n"
    if label == "current" and "candidate_prefetch_busy" in body:
        # 展开相关的中间条件，完整状态比较仍使用同一组公开输出和寄存器。
        for name in ("candidate_set", "select_metadata_busy", "select_launch"):
            body = re.sub(r"\b" + name + r"\b", "formal_current_" + name, body)
    if label == "current" and "g_saved_lookup_valid" in body:
        # 查询有效位在接收边沿保存，原始读取地址和数据使用独立的中间信号名称。
        body = body.replace("valid_i_rd_addr", "prepared_valid_i_rd_addr")
        body = body.replace("valid_o_rd_data", "prepared_valid_o_rd_data")
        body = body.replace(") u_valid (", ") u_valid_prepare (")
    return source[:first] + body + source[end:]


def restore_valid_storage_names(sets, ways):
    """将有效位存储恢复为共同名称，继续比较展开后的全部存储位。"""
    return ["cd conv_windowed_cache"] + [
        f"rename g_metadata_way[{way}].u_valid_prepare.mem[{row}] "
        f"g_metadata_way[{way}].u_valid.mem[{row}]"
        for way in range(ways) for row in range(sets)
    ] + ["cd .."]


def prove_caches(out, paths, helpers, profiles, read_width=32, line_bytes=16, payload_when_valid=False):
    observed = {}
    for label, path in paths.items():
        target = out / (label + "_observed.sv")
        target.write_text(observed_cache(path.read_text(), label, payload_when_valid))
        observed[label] = target
    results = []
    for profile in profiles:
        sets, ways, depth = map(int, profile.split(":"))
        name = f"cache_s{sets}_w{ways}_d{depth}_r{read_width}_l{line_bytes}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        commands = []
        for label, path in observed.items():
            files = " ".join(shlex.quote(str(item)) for item in [path] + helpers)
            commands += ["read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top conv_windowed_cache "
                f"-GSETS={sets} -GWAYS={ways} -GDEMAND_DEPTH={depth} -GLINE_BYTES={line_bytes} "
                f"-GBUS_WIDTH=64 -GREAD_WIDTH={read_width} -Gp_defer_retire_shift=1 " + files,
                "prep -top conv_windowed_cache -flatten", "memory_map", "async2sync", "opt_clean"]
            if label == "current" and "g_saved_lookup_valid" in path.read_text():
                commands += restore_valid_storage_names(sets, ways)
            commands += [f"rename conv_windowed_cache {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 3", "equiv_status -assert"]
        script.write_text("\n".join(commands) + "\n")
        execute(script, log, "Equivalence successfully proven")
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
        results.append(dict(SETS=sets, WAYS=ways, DEMAND_DEPTH=depth,
                            READ_WIDTH=read_width, LINE_BYTES=line_bytes, passed=True,
                            equivalent_bits=int(match[1]), log_sha256=digest(log)))
        print("CACHE_SEQUENTIAL_EQUIVALENCE_PASS", name, flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--out", type=Path, default=ROOT / "build/cache_receive_timing/formal")
    parser.add_argument("--profiles", nargs="+", default=["2:1:1", "4:2:4"])
    parser.add_argument("--read-width", type=int, default=32)
    parser.add_argument("--line-bytes", type=int, default=16)
    parser.add_argument("--payload-when-valid", action="store_true",
                        help="公开数据仅在有效响应时比较，队列保存数据仍按实际写入检查")
    args = parser.parse_args()
    out = args.out.resolve()
    _, paths, helpers, manifest = prepare_inputs(out, args.reference, args.candidate)
    report = {"passed": False, "inputs": manifest, "input_assumptions": [],
              "response_profiles": prove_response(out, paths, args.payload_when_valid),
              "selection_profiles": prove_selection(out, paths, execute),
              "complete_cache_profiles": prove_caches(out, paths, helpers, args.profiles,
                                                       args.read_width, args.line_bytes,
                                                       args.payload_when_valid)}
    check_sources(manifest)
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(out / "summary.json")


if __name__ == "__main__":
    main()
