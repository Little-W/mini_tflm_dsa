#!/usr/bin/env python3
"""证明缓存预读描述符和字地址匹配结果的组合等价性。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/dma/cache/conv_read_cache.sv"
PARAMETERS = ("parameter int DEMAND_DEPTH=4, SI=7, "
    "DQ_AW=DEMAND_DEPTH<=1 ? 1 : $clog2(DEMAND_DEPTH), "
    "DQ_CW=$clog2(DEMAND_DEPTH+1), DW=131+SI")
PORTS = """input logic [DEMAND_DEPTH*DW-1:0] i_queue,
input logic [DW-1:0] i_incoming, i_work,
input logic [DQ_AW-1:0] request_head,
input logic [DQ_CW-1:0] request_count,
input logic [1:0] fg_state,
input logic req_fire, req_valid,
input logic [31:0] demand_addr,
input logic [SI-1:0] lookup_set"""
CONNECTIONS = ",".join("." + name + "(" + name + ")" for name in (
    "i_queue", "i_incoming", "i_work", "request_head", "request_count", "fg_state",
    "req_fire", "req_valid", "demand_addr", "lookup_set"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unit(name, source):
    start = source.index("  typedef struct packed {", source.index("module conv_windowed_cache"))
    end = source.index("  demand_t request_queue", start)
    types = source[start:end]
    start = source.index("  always_comb begin\n    lookup_read_request = request_count")
    end = source.index("  // 两种请求分别匹配已有快照", start)
    lookup = source[start:end]
    helpers = ""
    if "  logic [1:0] lookup_head_matches" in source:
        start = source.index("  logic [1:0] lookup_head_matches")
        end = source.index("  logic [READ_WIDTH-1:0] response_queue_data", start)
        helpers += source[start:end]
        start = source.index("  // 各个队列位置先比较字地址")
        end = source.index("  // 地址范围结果随接收描述保存", start)
        helpers += source[start:end]
    assignments = []
    for signal in ("work_word_matches_q", "demand_word_matches_q"):
        expression = re.search(r"\b" + signal + r"\s*<=\s*(.*?);", source, re.S)
        if expression is None:
            raise RuntimeError("找不到匹配寄存器更新表达式: " + signal)
        assignments.append("assign " + signal + " = " + expression[1] + ";")
    return "module " + name + " #(" + PARAMETERS + ")(\n" + PORTS + \
        ",\noutput logic [DW+SI+31:0] observed);\n" + types + """
localparam logic [1:0] FG_MISS=2'd1;
demand_t request_queue[DEMAND_DEPTH], incoming_request, work_request, lookup_read_request;
logic [SI-1:0] lookup_read_set;
logic [31:2] lookup_read_word;
logic work_word_matches_q, demand_word_matches_q;
assign incoming_request=i_incoming;
assign work_request=i_work;
for (genvar index=0; index<DEMAND_DEPTH; index++) begin : g_queue
  assign request_queue[index]=i_queue[index*DW+:DW];
end
""" + helpers + lookup + "\n".join(assignments) + """
assign observed={lookup_read_request, lookup_read_set, lookup_read_word,
                 work_word_matches_q, demand_word_matches_q};
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="4dee27ffec4dc891daf2681379f8b3fd27fd41f2")
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.candidate.read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE], cwd=ROOT, text=True)
    sources = {"reference": reference, "candidate": current}
    units = {label: unit(label, text) for label, text in sources.items()}
    miter = "\n".join(units.values()) + "module comparison #(" + PARAMETERS + ")(\n" + PORTS + \
        ",\noutput logic equivalent);\nlogic [DW+SI+31:0] expected, actual;\n"
    for label, target in (("reference", "expected"), ("candidate", "actual")):
        miter += label + " #(.DEMAND_DEPTH(DEMAND_DEPTH),.SI(SI)) u_" + label + "(" + \
            CONNECTIONS + ",.observed(" + target + "));\n"
    miter += "assign equivalent=expected==actual;\nendmodule\n"
    proof = out / "comparison.sv"
    proof.write_text(miter)
    results = []
    for depth, index_width in ((1, 1), (1, 7), (2, 1), (2, 7), (4, 7), (8, 7)):
        label = f"d{depth}_si{index_width}"
        script, log = out / (label + ".ys"), out / (label + ".log")
        # 单项队列的指针在 RTL 中始终写入零，其余配置保留全部输入取值。
        constraints = "-set request_head 0 " if depth == 1 else ""
        script.write_text("read_slang --top comparison " + f"-GDEMAND_DEPTH={depth} -GSI={index_width} " +
            shlex.quote(str(proof)) + "\nprep -top comparison -flatten\n" +
            "sat -verify -prove equivalent 1 " + constraints + "-show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("缓存组合等价证明未完成: " + label)
        results.append(dict(demand_depth=depth, set_index_width=index_width, passed=True,
            constraints={"request_head": 0} if depth == 1 else {}, log_sha256=digest(log.read_bytes())))
        print("CACHE_LOOKUP_EQUIVALENCE_PASS", label, flush=True)
    cases = {}
    for label, source in sources.items():
        target = out / (label + "_cache.sv")
        target.write_text(source)
        for depth in (1, 4):
            cases[label + "_cache_d" + str(depth)] = dict(top="conv_windowed_cache",
                options=["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1", "-GSETS=128", "-GWAYS=2",
                    "-GLINE_BYTES=16", "-GBUS_WIDTH=64", "-GREAD_WIDTH=32", "-Gp_defer_retire_shift=1",
                    "-GDEMAND_DEPTH=" + str(depth)],
                sources=[str(target), "rtl/npu/dma/cache/conv_sdp_ram.sv",
                    "rtl/npu/conv/conv_axi_span_reader.sv", "rtl/npu/conv/conv_axi_read_guard.sv"],
                configuration=f"128 组、2 路、16 字节缓存行、64 位 AXI、{depth} 个需求请求名额")
    if current != args.candidate.read_text():
        raise RuntimeError("证明期间缓存源码发生变化")
    report = dict(passed=True, reference=args.reference, source_sha256=digest(current.encode()),
        reference_sha256=digest(reference.encode()), cases=results,
        compared_outputs=["lookup_read_request", "lookup_read_set", "lookup_read_word",
            "work_word_matches_q", "demand_word_matches_q"])
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (out / "synthesis_cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
