#!/usr/bin/env python3
"""从实际源码检查替换选择、元数据冲突和快照状态的组合等价。"""
from __future__ import annotations

import re
import shlex

from support import digest

PARAMETERS = "parameter int SI=7,WI=1"
PORTS = """input logic rst_n,cfg_valid,cfg_ready,select_launch_candidate,
input logic [1:0] fg_state,fill_state,
input logic req_fire,lookup_hit,lookup_ready,lookup_range,
input logic select_stage_valid,select_decision_valid,select_prefetch,
input logic pf_pending,pf_match_ready,pf_hit,pf_in_flight,
input logic bypass_q,completing_demand,
input logic span_rsp_valid,span_rsp_ready,span_last,fill_bad,span_error,
input logic hint_pending_q,hint_effective_valid,candidate_prefetch,
input logic [31:0] pf_addr,select_addr,demand_addr,
input logic [SI-1:0] lookup_set,select_set,fill_set,hint_set,pf_set,demand_set,
input logic [WI-1:0] select_way,lookup_way,fill_way"""
NAMES = []
for line in PORTS.splitlines():
    line = re.sub(r"^input logic(?: \[[^\]]+\])? ", "", line).strip(",")
    NAMES.extend(line.split(","))


def assignment(source, name):
    match = re.search(r"  assign " + name + r"\s*=.*?;", source, re.S)
    if match is None:
        raise RuntimeError("找不到实际信号表达式: " + name)
    return match[0]


def model(label, source):
    first = source.index("    select_launch =")
    end = source.index(";", first) + 1
    launch = source[first:end]
    first = source.index("    if (select_launch &&", end)
    end = source.index("    // A pending miss", first)
    launch += source[first:end]
    if "candidate_prefetch_busy" in source:
        first = source.index("  logic candidate_prefetch_busy")
        end = source.index("  assign select_metadata_busy", first)
        candidate = source[first:end]
    else:
        candidate = assignment(source, "candidate_metadata_busy")
    text = f"module {label} #({PARAMETERS})({PORTS},output logic [2:0] observed);\n"
    text += """localparam logic [1:0] FG_MISS=1,F_IDLE=0,F_DATA=2;
logic fill_complete,fill_success,metadata_fill,select_metadata_busy,candidate_metadata_busy;
logic select_launch,select_capture,stage_next;
logic [SI-1:0] candidate_set;
"""
    text += "\n".join(assignment(source, name) for name in
        ("fill_complete", "fill_success", "select_metadata_busy", "select_capture")) + "\n"
    match = re.search(r"  wire metadata_fill=(.*?);", source, re.S)
    if match is None:
        raise RuntimeError("找不到元数据填充表达式")
    text += "assign metadata_fill=" + match[1] + ";\n"
    match = re.search(r"    candidate_set = (.*?);", source, re.S)
    if match is None:
        raise RuntimeError("找不到候选组号选择表达式")
    text += "assign candidate_set=" + match[1] + ";\n"
    first = source.index("  always_ff @(posedge clk or negedge rst_n) begin\n"
                         "    if (!rst_n) begin\n      select_stage_valid")
    if "  logic select_snapshot_usable" in source:
        first = source.index("  logic select_snapshot_usable")
    end = source.index("  // Separate synchronous metadata", first)
    state = source[first:end].replace(
        "always_ff @(posedge clk or negedge rst_n) begin",
        "always_comb begin\n    stage_next=select_stage_valid;")
    state = state.replace("select_stage_valid <=", "stage_next =")
    return text + candidate + "\nalways_comb begin\n" + launch + "\nend\n" + state + \
        "\nassign observed={stage_next,select_launch,candidate_metadata_busy};\nendmodule\n"


def prove(out, paths, execute):
    text = "".join(model(label, path.read_text()) for label, path in paths.items())
    text += f"module comparison #({PARAMETERS})({PORTS},output logic equivalent);\n"
    text += "logic [2:0] expected,actual;\n"
    connections = ",".join(f".{name}({name})" for name in NAMES)
    for label, result in (("reference", "expected"), ("current", "actual")):
        text += f"{label} #(.SI(SI),.WI(WI)) u_{label}({connections},.observed({result}));\n"
    text += "assign equivalent=expected==actual;\nendmodule\n"
    source = out / "selection_comparison.sv"
    source.write_text(text)
    results = []
    for index_width, way_width in ((1,1), (7,1), (7,2), (9,3)):
        name = f"selection_si{index_width}_wi{way_width}"
        script, log = out / (name + ".ys"), out / (name + ".log")
        script.write_text(f"read_slang --top comparison -GSI={index_width} -GWI={way_width} " +
            shlex.quote(str(source)) + "\nprep -top comparison -flatten\n"
            "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        execute(script, log, "SUCCESS!")
        results.append(dict(SI=index_width, WI=way_width, passed=True, log_sha256=digest(log)))
        print("CACHE_SELECTION_EQUIVALENCE_PASS", name, flush=True)
    return results
